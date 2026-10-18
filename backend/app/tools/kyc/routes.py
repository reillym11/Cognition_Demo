from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, exports
from app.foundation.authz import Principal, require
from app.foundation.datacls import keyed_hash
from app.foundation.db import get_db, utcnow
from app.foundation.models import ApprovalRequest, AuditEvent
from app.tools.kyc import service
from app.tools.kyc.models import OPEN_STATUSES, KycCase

router = APIRouter(prefix="/api/kyc", tags=["kyc"])

SORTS = {
    "sla_due_at": KycCase.sla_due_at,
    "created_at": KycCase.created_at,
    "vendor_score": KycCase.vendor_score,
    "ref": KycCase.ref,
    "risk_level": KycCase.risk_level,
}


class ReasonBody(BaseModel):
    reason: str | None = None


class RecommendBody(BaseModel):
    decision: Literal["approve", "reject"]
    reason_code: str
    reason: str | None = None


class RevealBody(BaseModel):
    field: str
    reason: str | None = None


class QaBody(BaseModel):
    result: Literal["passed", "failed"]
    reason: str | None = None


def _filtered(
    p: Principal,
    status: str | None,
    risk: str | None,
    q: str | None,
    sla: str | None,
    assigned: str | None,
    region: str | None,
) -> Any:
    stmt = service.scoped(select(KycCase), p)
    if status == "open":
        stmt = stmt.where(KycCase.status.in_(OPEN_STATUSES))
    elif status:
        stmt = stmt.where(KycCase.status == status)
    if risk:
        stmt = stmt.where(KycCase.risk_level == risk)
    if region:
        stmt = stmt.where(KycCase.region == region)
    if q:
        stmt = stmt.where(or_(KycCase.ref == q.strip().upper(), KycCase.ref.ilike(f"%{q.strip()}%")))
    if sla == "breached":
        stmt = stmt.where(KycCase.status.in_(OPEN_STATUSES), KycCase.sla_due_at < utcnow())
    if assigned == "me":
        stmt = stmt.where(KycCase.assigned_to == p.oid)
    elif assigned == "unassigned":
        stmt = stmt.where(KycCase.assigned_to.is_(None))
    return stmt


@router.get("/cases")
def list_cases(
    p: Principal = Depends(require("kyc.case.read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    risk: str | None = None,
    q: str | None = None,
    sla: str | None = None,
    assigned: str | None = None,
    region: str | None = None,
    sort: str = "sla_due_at",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    from sqlalchemy import func

    stmt = _filtered(p, status, risk, q, sla, assigned, region)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    col = SORTS.get(sort.lstrip("-"), KycCase.sla_due_at)
    stmt = (
        stmt.order_by(col.desc() if sort.startswith("-") else col.asc(), KycCase.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = db.execute(stmt).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [service.to_dict(c) for c in rows]}


@router.get("/stats")
def stats(p: Principal = Depends(require("kyc.case.read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.stats(db, p)


@router.get("/cases/{case_id}")
def get_case(
    case_id: int, p: Principal = Depends(require("kyc.case.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    c = service.get_case(db, p, case_id)
    req = db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.subject_type == service.RES, ApprovalRequest.subject_id == str(c.id))
        .order_by(ApprovalRequest.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "case": service.to_dict(c),
        "approval": approvals.to_dict(req, approvals.decisions_for(db, req.id), p) if req else None,
        "can": {
            "claim": p.has("kyc.case.work")
            and c.status in ("new", "info_requested")
            and c.assigned_to in (None, p.oid)
            and (not service.needs_senior(c) or p.has("kyc.decide_high")),
            "work": c.assigned_to == p.oid and c.status in ("in_review", "info_requested"),
            "reveal": p.has("kyc.pii.reveal"),
        },
        "reason_codes": {"approve": sorted(service.APPROVE_CODES), "reject": sorted(service.REJECT_CODES)},
    }


@router.get("/cases/{case_id}/audit")
def case_audit(
    case_id: int, p: Principal = Depends(require("kyc.case.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    service.get_case(db, p, case_id)
    rows = (
        db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.chain == service.CHAIN,
                AuditEvent.resource == service.RES,
                AuditEvent.resource_id == str(case_id),
            )
            .order_by(AuditEvent.seq)
        )
        .scalars()
        .all()
    )
    return [audit.to_dict(e) for e in rows]


@router.post("/cases/{case_id}/claim")
def claim(
    case_id: int, p: Principal = Depends(require("kyc.case.work")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.to_dict(service.claim(db, p, case_id))


@router.post("/cases/{case_id}/release")
def release(
    case_id: int,
    body: ReasonBody,
    p: Principal = Depends(require("kyc.case.work")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.release(db, p, case_id, body.reason))


@router.post("/cases/{case_id}/recommend")
def recommend(
    case_id: int,
    body: RecommendBody,
    p: Principal = Depends(require("kyc.case.work")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.recommend(db, p, case_id, body.decision, body.reason_code, body.reason))


@router.post("/cases/{case_id}/request-info")
def request_info(
    case_id: int,
    body: ReasonBody,
    p: Principal = Depends(require("kyc.case.work")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.request_info(db, p, case_id, body.reason))


@router.post("/cases/{case_id}/info-received")
def info_received(
    case_id: int,
    body: ReasonBody,
    p: Principal = Depends(require("kyc.case.work")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.info_received(db, p, case_id, body.reason))


@router.post("/cases/{case_id}/escalate")
def escalate(
    case_id: int,
    body: ReasonBody,
    p: Principal = Depends(require("kyc.case.work")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.escalate(db, p, case_id, body.reason))


@router.post("/cases/{case_id}/reveal")
def reveal(
    case_id: int,
    body: RevealBody,
    p: Principal = Depends(require("kyc.pii.reveal")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return {"value": service.reveal(db, p, case_id, body.field, body.reason)}


@router.get("/qa")
def qa_queue(
    p: Principal = Depends(require("kyc.qa.review")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            service.scoped(
                select(KycCase).where(KycCase.qa_status == "pending").order_by(KycCase.decided_at).limit(200),
                p,
            )
        )
        .scalars()
        .all()
    )
    return [service.to_dict(c) for c in rows]


@router.post("/cases/{case_id}/qa")
def qa_review(
    case_id: int,
    body: QaBody,
    p: Principal = Depends(require("kyc.qa.review")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.qa_review(db, p, case_id, body.result, body.reason))


@router.post("/fastlane/run")
def fastlane_run(
    body: ReasonBody, p: Principal = Depends(require("kyc.fastlane.run")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    from app.foundation import jobs

    audit.record(
        db,
        p,
        "kyc.fastlane_triggered",
        "job",
        "kyc.fastlane",
        chain=service.CHAIN,
        reason=body.reason or "manual run",
    )
    jobs.enqueue(db, "kyc.fastlane", {}, dedupe_key="kyc.fastlane:manual")
    return {"queued": True}


@router.get("/export")
def export(
    p: Principal = Depends(require("kyc.export")),
    db: Session = Depends(get_db),
    reason: str | None = None,
    status: str | None = None,
    risk: str | None = None,
    sla: str | None = None,
    region: str | None = None,
) -> Any:
    rows = db.execute(_filtered(p, status, risk, None, sla, None, region).order_by(KycCase.id)).scalars()
    return exports.csv_export(
        db,
        p,
        resource=service.RES,
        rows=(service.to_dict(c) for c in rows),
        columns=[
            "ref",
            "applicant_name",
            "email",
            "region",
            "risk_level",
            "status",
            "decision_code",
            "sla_due_at",
            "sla_breached",
        ],
        filename="kyc-queue",
        reason=reason,
        chain=service.CHAIN,
        filters={"status": status, "risk": risk, "sla": sla, "region": region},
    )


_ = keyed_hash
