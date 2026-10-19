from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.foundation import audit, exports
from app.foundation.authz import Principal, require
from app.foundation.db import get_db, utcnow
from app.foundation.errors import Forbidden
from app.foundation.models import AuditEvent
from app.foundation.ratelimit import sensitive_rate_limit
from app.tools.complaints import service
from app.tools.complaints.models import Complaint

router = APIRouter(prefix="/api/complaints", tags=["complaints"])
SORTS = {"received_at": Complaint.received_at, "stage_due_at": Complaint.stage_due_at, "ref": Complaint.ref}


class UpdateBody(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    checks: dict[str, bool] = Field(default_factory=dict)
    reason: str | None = None


class ReasonBody(BaseModel):
    reason: str | None = None


class LinkBody(BaseModel):
    kind: str
    id: int
    reason: str | None = None


class RevealBody(BaseModel):
    field: str
    reason: str | None = None


def _can_progress(p: Principal) -> Principal:
    if not (p.has("complaints.work") or p.has("complaints.compliance_review")):
        raise Forbidden("missing permission: complaints.work or complaints.compliance_review")
    return p


def _filtered(
    p: Principal,
    status: str | None,
    stage: str | None,
    regulatory: str | None,
    overdue: str | None,
    mine: str | None,
    q: str | None,
    category: str | None,
) -> Any:
    s = select(Complaint)
    if status:
        s = s.where(Complaint.status == status)
    if stage:
        s = s.where(Complaint.stage == stage, Complaint.status == "open")
    if category:
        s = s.where(Complaint.category == category)
    if regulatory:
        s = s.where(or_(Complaint.regulatory, Complaint.unfair_treatment))
    if overdue:
        s = s.where(Complaint.status == "open", Complaint.stage_due_at < utcnow())
    if mine:
        s = s.where(Complaint.assigned_to == p.oid)
    if q:
        s = s.where(or_(Complaint.ref.ilike(f"%{q.strip()}%"), Complaint.summary.ilike(f"%{q.strip()}%")))
    return s


@router.get("")
def list_complaints(
    p: Principal = Depends(require("complaints.read")),
    db: Session = Depends(get_db),
    status: str | None = "open",
    stage: str | None = None,
    regulatory: str | None = None,
    overdue: str | None = None,
    mine: str | None = None,
    q: str | None = None,
    category: str | None = None,
    sort: str = "stage_due_at",
    desc: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    s = _filtered(p, status or None, stage, regulatory, overdue, mine, q, category)
    total = db.execute(select(func.count()).select_from(s.subquery())).scalar_one()
    col = SORTS.get(sort, Complaint.stage_due_at)
    rows = db.execute(
        s.order_by(col.desc() if desc else col, Complaint.id).offset((page - 1) * page_size).limit(page_size)
    ).scalars()
    now = utcnow()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [service.to_dict(c, now=now) for c in rows],
    }


@router.get("/meta")
def meta(p: Principal = Depends(require("complaints.read"))) -> dict[str, Any]:
    return {
        "categories": service.CATEGORIES,
        "products": service.PRODUCTS,
        "root_causes": service.ROOT_CAUSES,
        "stages": [
            {"key": s.key, "label": s.label}
            for s in [*service.WF.stages[:4], service.COMPLIANCE, service.WF.stages[4]]
        ],
    }


@router.get("/aging")
def aging(
    p: Principal = Depends(require("complaints.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.aging(db)


@router.get("/register.csv", dependencies=[sensitive_rate_limit])
def register(
    p: Principal = Depends(require("complaints.export")),
    db: Session = Depends(get_db),
    reason: str | None = None,
    status: str | None = None,
    regulatory: str | None = None,
) -> Any:
    rows = db.execute(
        _filtered(p, status, None, regulatory, None, None, None, None).order_by(Complaint.received_at)
    ).scalars()
    return exports.csv_export(
        db,
        p,
        resource=service.RES,
        rows=(service.to_dict(c) for c in rows),
        columns=[
            "ref",
            "received_at",
            "channel",
            "product",
            "category",
            "regulatory",
            "unfair_treatment",
            "root_cause",
            "stage_label",
            "status",
            "closed_at",
            "age_days",
            "customer_name",
        ],
        filename="complaint-register.csv",
        reason=reason,
        chain=service.CHAIN,
        filters={"status": status, "regulatory": regulatory},
    )


@router.get("/{cid}")
def detail(
    cid: int, p: Principal = Depends(require("complaints.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    c = service.get(db, cid)
    d = service.to_dict(c)
    d["can"] = {
        "work": p.has("complaints.work")
        and c.status == "open"
        and c.assigned_to == p.oid
        and c.stage != "compliance_review",
        "claim": p.has("complaints.work")
        and c.status == "open"
        and not c.assigned_to
        and c.stage != "compliance_review",
        "compliance": p.has("complaints.compliance_review")
        and c.stage == "compliance_review"
        and c.status == "open",
        "reveal": p.has("complaints.pii.reveal"),
    }
    return d


@router.get("/{cid}/audit")
def case_audit(
    cid: int, p: Principal = Depends(require("complaints.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    service.get(db, cid)
    rows = db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.chain == service.CHAIN,
            AuditEvent.resource == service.RES,
            AuditEvent.resource_id == str(cid),
        )
        .order_by(AuditEvent.seq)
    ).scalars()
    return [audit.to_dict(e) for e in rows]


@router.post("/{cid}/claim")
def claim(
    cid: int, p: Principal = Depends(require("complaints.work")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.to_dict(service.claim(db, p, cid))


@router.patch("/{cid}")
def update(
    cid: int,
    body: UpdateBody,
    p: Principal = Depends(require("complaints.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.update(db, _can_progress(p), cid, body.fields, body.checks, body.reason))


@router.post("/{cid}/advance")
def advance(
    cid: int,
    body: ReasonBody,
    p: Principal = Depends(require("complaints.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.advance(db, _can_progress(p), cid, body.reason))


@router.post("/{cid}/links")
def link(
    cid: int,
    body: LinkBody,
    p: Principal = Depends(require("complaints.work")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.to_dict(service.link(db, p, cid, body.kind, body.id, body.reason))


@router.post("/{cid}/reveal", dependencies=[sensitive_rate_limit])
def reveal(
    cid: int,
    body: RevealBody,
    p: Principal = Depends(require("complaints.pii.reveal")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return {"value": service.reveal(db, p, cid, body.field, body.reason)}
