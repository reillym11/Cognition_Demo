from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, exports
from app.foundation.authz import Principal, require
from app.foundation.db import get_db
from app.foundation.models import ApprovalRequest, AuditEvent
from app.foundation.ratelimit import sensitive_rate_limit
from app.tools.refunds import service
from app.tools.refunds.models import Refund, Transaction

router = APIRouter(prefix="/api/refunds", tags=["refunds"])

TXN_SORTS = {
    "charge_id": Transaction.charge_id,
    "amount_cents": Transaction.amount_cents,
    "captured_at": Transaction.captured_at,
}
REFUND_SORTS = {"id": Refund.id, "amount_cents": Refund.amount_cents, "created_at": Refund.created_at}


class RefundBody(BaseModel):
    amount_cents: int
    reason_code: str
    reason: str | None = None


class ReasonBody(BaseModel):
    reason: str | None = None


class RevealBody(BaseModel):
    field: str
    reason: str | None = None


def _page(db: Session, stmt: Any, col: Any, desc: bool, page: int, page_size: int) -> tuple[int, list[Any]]:
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(col.desc() if desc else col.asc()).offset((page - 1) * page_size).limit(page_size)
        )
        .scalars()
        .all()
    )
    return total, list(rows)


@router.get("/transactions")
def list_transactions(
    p: Principal = Depends(require("refunds.read")),
    db: Session = Depends(get_db),
    q: str | None = None,
    sort: str = "-captured_at",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    stmt = service.scoped(select(Transaction), p)
    if q:
        s = q.strip()
        stmt = stmt.where(or_(Transaction.charge_id == s, Transaction.merchant.ilike(f"%{s}%")))
    col = TXN_SORTS.get(sort.lstrip("-"), Transaction.captured_at)
    total, rows = _page(db, stmt, col, sort.startswith("-"), page, page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [service.txn_dict(t) for t in rows],
    }


@router.get("/transactions/{txn_id}")
def get_transaction(
    txn_id: int, p: Principal = Depends(require("refunds.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = service.get_txn(db, p, txn_id)
    refunds = db.execute(select(Refund).where(Refund.transaction_id == t.id).order_by(Refund.id)).scalars()
    return {
        "transaction": service.txn_dict(t, service.reserved_cents(db, t.id)),
        "refunds": [service.refund_dict(r) for r in refunds],
        "reason_codes": sorted(service.REASON_CODES),
        "can_reveal": p.has("refunds.pii.reveal"),
    }


@router.post("/transactions/{txn_id}/refunds")
def create_refund(
    txn_id: int,
    body: RefundBody,
    p: Principal = Depends(require("refunds.request")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    r = service.request_refund(db, p, txn_id, body.amount_cents, body.reason_code, body.reason)
    return service.refund_dict(r)


@router.post("/transactions/{txn_id}/reveal", dependencies=[sensitive_rate_limit])
def reveal(
    txn_id: int,
    body: RevealBody,
    p: Principal = Depends(require("refunds.pii.reveal")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return {"value": service.reveal(db, p, txn_id, body.field, body.reason)}


def _refunds_filtered(p: Principal, status: str | None, mine: str | None) -> Any:
    stmt = service.scoped(select(Refund).join(Transaction), p)
    if status:
        stmt = stmt.where(Refund.status == status)
    if mine:
        stmt = stmt.where(Refund.requested_by == p.oid)
    return stmt


@router.get("/requests")
def list_refunds(
    p: Principal = Depends(require("refunds.read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    mine: str | None = None,
    sort: str = "-id",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    col = REFUND_SORTS.get(sort.lstrip("-"), Refund.id)
    total, rows = _page(db, _refunds_filtered(p, status, mine), col, sort.startswith("-"), page, page_size)
    txns = {
        t.id: t
        for t in db.execute(
            select(Transaction).where(Transaction.id.in_({r.transaction_id for r in rows}))
        ).scalars()
    }
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [service.refund_dict(r, txns[r.transaction_id]) for r in rows],
    }


@router.get("/stats")
def stats(p: Principal = Depends(require("refunds.read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.stats(db, p)


@router.get("/export", dependencies=[sensitive_rate_limit])
def export(
    p: Principal = Depends(require("refunds.export")),
    db: Session = Depends(get_db),
    reason: str | None = None,
    status: str | None = None,
    mine: str | None = None,
) -> Any:
    rows = db.execute(_refunds_filtered(p, status, mine).add_columns(Transaction).order_by(Refund.id)).all()
    return exports.csv_export(
        db,
        p,
        resource=service.RES,
        rows=(service.refund_dict(r, t) for r, t in rows),
        columns=[
            "id",
            "charge_id",
            "merchant",
            "amount",
            "currency",
            "status",
            "reason_code",
            "requested_by_name",
            "processor_ref",
            "created_at",
            "executed_at",
        ],
        filename="refunds",
        reason=reason,
        chain=service.CHAIN,
        filters={"status": status, "mine": mine},
    )


@router.get("/requests/{refund_id}")
def get_refund(
    refund_id: int, p: Principal = Depends(require("refunds.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    r = service.get_refund(db, p, refund_id)
    t = service.get_txn(db, p, r.transaction_id)
    req = db.get(ApprovalRequest, r.approval_request_id) if r.approval_request_id else None
    return {
        "refund": service.refund_dict(r, t),
        "approval": approvals.to_dict(req, approvals.decisions_for(db, req.id), p) if req else None,
    }


@router.get("/requests/{refund_id}/audit")
def refund_audit(
    refund_id: int, p: Principal = Depends(require("refunds.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    r = service.get_refund(db, p, refund_id)
    conds = [(AuditEvent.resource == service.RES) & (AuditEvent.resource_id == str(r.id))]
    if r.approval_request_id:
        conds.append(
            (AuditEvent.resource == "approval") & (AuditEvent.resource_id == str(r.approval_request_id))
        )
    rows = db.execute(select(AuditEvent).where(or_(*conds)).order_by(AuditEvent.seq)).scalars()
    return [audit.to_dict(e) for e in rows]


@router.post("/requests/{refund_id}/reconcile")
def reconcile(
    refund_id: int,
    body: ReasonBody,
    p: Principal = Depends(require("refunds.reconcile")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.refund_dict(service.request_reconcile(db, p, refund_id, body.reason))
