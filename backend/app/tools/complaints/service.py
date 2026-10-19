"""Complaints case management on the shared stage engine. Regulatory / unfair-treatment complaints get a
compliance-review stage that must be completed by Compliance, by someone other than the investigator."""

from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.foundation import audit, workflow
from app.foundation.adapters.directory import get_directory
from app.foundation.authz import Principal
from app.foundation.datacls import mask_record
from app.foundation.db import utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid, NotFound, require_reason
from app.foundation.workflow import Branch, StageDef, WorkflowDef

RES = "complaint"
CHAIN = "complaints"
PII_FIELDS = {"customer_name", "customer_email"}
CHANNELS = ("phone", "email", "chat", "letter", "social")
PRODUCTS = ("cards", "payments", "payouts", "onboarding", "refunds", "fees")
CATEGORIES = (
    "fees_charges",
    "service_quality",
    "fraud_dispute",
    "account_access",
    "delay",
    "communication",
    "kyc_onboarding",
)
ROOT_CAUSES = {
    "process": ["process.missing_step", "process.wrong_policy_applied", "process.manual_error"],
    "system": ["system.outage", "system.defect", "system.integration_failure"],
    "people": ["people.training_gap", "people.conduct"],
    "third_party": ["third_party.processor", "third_party.vendor"],
    "customer": ["customer.misunderstanding", "customer.not_upheld"],
}
ALL_ROOT_CAUSES = {rc for v in ROOT_CAUSES.values() for rc in v}

COMPLIANCE = StageDef(
    "compliance_review",
    "Compliance review",
    72,
    required_fields=("compliance_notes",),
    permission="complaints.compliance_review",
    separate_from=("investigate", "resolve"),
)
WF = WorkflowDef(
    key="complaints",
    stages=(
        StageDef("intake", "Intake", 24, required_fields=("product", "summary")),
        StageDef("classify", "Classify", 48, required_fields=("category",)),
        StageDef(
            "investigate",
            "Investigate",
            240,
            required_fields=("root_cause",),
            checklist=("contacted_customer", "reviewed_records"),
        ),
        StageDef("resolve", "Resolve", 120, required_fields=("resolution",)),
        StageDef(
            "respond",
            "Customer response",
            48,
            required_fields=("response_text",),
            checklist=("response_sent",),
        ),
    ),
    branches=(
        Branch(
            "resolve",
            lambda d: bool(d.get("regulatory") or d.get("unfair_treatment")),
            (COMPLIANCE,),
            "Regulatory or unfair-treatment tag",
        ),
    ),
)
# which fields can be edited while a case sits in a stage. Earlier-stage fields stay editable until close,
# except that compliance review freezes everything before it (see editable_fields).
STAGE_FIELDS = {
    "intake": {"product", "summary", "channel"},
    "classify": {"category", "regulatory", "unfair_treatment"},
    "investigate": {"root_cause"},
    "resolve": {"resolution"},
    "compliance_review": {"compliance_notes"},
    "respond": {"response_text"},
}


def data_of(c: Any) -> dict[str, Any]:
    return {f: getattr(c, f) for fs in STAGE_FIELDS.values() for f in fs}


def path_keys(c: Any) -> list[str]:
    return [s.key for s in WF.path(data_of(c))]


def editable_fields(c: Any) -> set[str]:
    keys = path_keys(c)
    cur = keys.index(c.stage)
    start = 0
    if COMPLIANCE.key in keys:
        review = keys.index(COMPLIANCE.key)
        if cur == review:
            start = review
        elif cur > review:
            start = review + 1
    return set().union(*(STAGE_FIELDS[k] for k in keys[start : cur + 1]))


def to_dict(c: Any, *, now: Any = None) -> dict[str, Any]:
    now = now or utcnow()
    d = {
        "id": c.id,
        "ref": c.ref,
        "customer_name": c.customer_name,
        "customer_email": c.customer_email,
        "channel": c.channel,
        "description": c.description,
        **data_of(c),
        "stage": c.stage,
        "status": c.status,
        "stage_label": WF.stage(c.stage).label if c.status == "open" else "Closed",
        "stage_entered_at": c.stage_entered_at.isoformat(),
        "stage_due_at": c.stage_due_at.isoformat() if c.status == "open" else None,
        "overdue": c.status == "open" and c.stage_due_at < now,
        "assigned_to": c.assigned_to,
        "assigned_name": c.assigned_name,
        "checks": c.checks,
        "completers": c.completers,
        "related": c.related,
        "received_at": c.received_at.isoformat(),
        "closed_at": c.closed_at.isoformat() if c.closed_at else None,
        "age_days": ((c.closed_at or now) - c.received_at).days,
        "path": [
            {
                "key": s.key,
                "label": s.label,
                "sla_hours": s.sla_hours,
                "required": list(s.required_fields),
                "checklist": list(s.checklist),
            }
            for s in WF.path(data_of(c))
        ],
    }
    return mask_record(RES, d)


def get(db: Session, cid: int, *, lock: bool = False) -> Any:
    from app.tools.complaints.models import Complaint

    q = select(Complaint).where(Complaint.id == cid)
    c = db.execute(q.with_for_update() if lock else q).scalar_one_or_none()
    if c is None:
        raise NotFound("complaint not found")
    return c


def _require_open(c: Any) -> None:
    if c.status != "open":
        raise Conflict("complaint is closed")


def _require_worker(c: Any, p: Principal) -> None:
    if c.stage == "compliance_review":
        if not p.has("complaints.compliance_review"):
            raise Forbidden("this case is awaiting compliance review")
    elif not p.has("complaints.work"):
        raise Forbidden("missing permission: complaints.work")
    elif c.assigned_to != p.oid:
        raise Forbidden("claim the complaint before working on it")


def _still_handler(oid: str | None) -> bool:
    """Re-check the directory before handing a case back: a stale completer may have lost the role."""
    from app.foundation.registry import get_registry

    if not oid:
        return False
    try:
        entry = get_directory().lookup(oid)
    except Exception:
        return False
    return bool(
        entry
        and entry.enabled
        and "complaints.work" in get_registry().permissions_for(frozenset(entry.roles))
    )


def claim(db: Session, p: Principal, cid: int) -> Any:
    c = get(db, cid, lock=True)
    _require_open(c)
    if c.stage == "compliance_review":
        raise Conflict("compliance review cases are worked from the compliance queue")
    if c.assigned_to and c.assigned_to != p.oid:
        raise Conflict(f"already claimed by {c.assigned_name}")
    c.assigned_to, c.assigned_name = p.oid, p.name
    audit.record(db, p, "complaint.claimed", RES, c.id, chain=CHAIN, after={"assigned_to": p.oid})
    return c


def update(
    db: Session, p: Principal, cid: int, fields: dict[str, Any], checks: dict[str, bool], reason: str | None
) -> Any:
    c = get(db, cid, lock=True)
    _require_open(c)
    _require_worker(c, p)
    bad = set(fields) - editable_fields(c)
    if bad:
        raise Invalid(f"fields not editable at stage '{c.stage}': {sorted(bad)}")
    if "category" in fields and fields["category"] not in CATEGORIES:
        raise Invalid(f"category must be one of {CATEGORIES}")
    if "root_cause" in fields and fields["root_cause"] not in ALL_ROOT_CAUSES:
        raise Invalid("root_cause must come from the taxonomy")
    if "product" in fields and fields["product"] not in PRODUCTS:
        raise Invalid(f"product must be one of {PRODUCTS}")
    stage_checks = set(WF.stage(c.stage).checklist)
    if set(checks) - stage_checks:
        raise Invalid(f"unknown checklist items for this stage: {sorted(set(checks) - stage_checks)}")
    if ("regulatory" in fields or "unfair_treatment" in fields) and c.stage != "classify":
        raise Invalid("regulatory tags are set at classification")
    before = {**data_of(c), "checks": dict(c.checks)}
    for k, v in fields.items():
        setattr(c, k, v.strip() if isinstance(v, str) else v)
    c.checks = {**c.checks, **{k: bool(v) for k, v in checks.items()}}
    after = {**data_of(c), "checks": dict(c.checks)}
    if before == after:
        raise Invalid("no change")
    reason = (
        require_reason(reason, "updating a complaint")
        if c.stage == "compliance_review"
        else (reason or "updated")
    )
    audit.record(
        db, p, "complaint.updated", RES, c.id, chain=CHAIN, reason=reason, before=before, after=after
    )
    return c


def advance(db: Session, p: Principal, cid: int, reason: str | None) -> Any:
    reason = require_reason(reason, "completing a stage")
    c = get(db, cid, lock=True)
    _require_open(c)
    _require_worker(c, p)
    now = utcnow()
    nxt, due = workflow.advance(WF, c.stage, data_of(c), c.checks, c.completers, p, now)
    done = c.stage
    c.completers = {**c.completers, done: p.oid}
    if nxt is None:
        c.status, c.closed_at, c.assigned_to, c.assigned_name = "closed", now, None, None
    else:
        c.stage, c.stage_entered_at, c.stage_due_at = nxt.key, now, due
        if nxt.key == "compliance_review":
            c.assigned_to = c.assigned_name = None
        elif done == "compliance_review":
            # hand back to whoever investigated, if they can still work complaints; else back to the queue
            investigator = c.completers.get("investigate")
            c.assigned_to = investigator if _still_handler(investigator) else None
            c.assigned_name = None
    audit.record(
        db,
        p,
        "complaint.stage_completed",
        RES,
        c.id,
        chain=CHAIN,
        reason=reason,
        before={"stage": done},
        after={"stage": c.stage, "status": c.status},
    )
    return c


def link(db: Session, p: Principal, cid: int, kind: str, ref_id: int, reason: str | None) -> Any:
    from app.tools.kyc.models import KycCase
    from app.tools.refunds.models import Refund

    reason = require_reason(reason, "linking a case")
    c = get(db, cid, lock=True)
    _require_worker(c, p)
    model = {"refund": Refund, "kyc": KycCase}.get(kind)
    if model is None:
        raise Invalid("kind must be refund or kyc")
    if db.get(model, ref_id) is None:
        raise NotFound(f"{kind} {ref_id} not found")
    if any(r["kind"] == kind and r["id"] == ref_id for r in c.related):
        raise Conflict("already linked")
    c.related = [*c.related, {"kind": kind, "id": ref_id}]
    audit.record(
        db, p, "complaint.linked", RES, c.id, chain=CHAIN, reason=reason, after={"kind": kind, "id": ref_id}
    )
    return c


def reveal(db: Session, p: Principal, cid: int, field: str, reason: str | None) -> str:
    reason = require_reason(reason, "revealing PII")
    if field not in PII_FIELDS:
        raise Invalid("not a revealable field")
    c = get(db, cid)
    audit.record(
        db, p, "complaint.pii_revealed", RES, c.id, chain=CHAIN, reason=reason, after={"field": field}
    )
    return str(getattr(c, field))


def aging(db: Session) -> dict[str, Any]:
    from app.tools.complaints.models import Complaint

    now = utcnow()
    age = func.extract("epoch", now - Complaint.received_at) / 86400
    bucket = case(
        (age <= 7, "0-7"), (age <= 14, "8-14"), (age <= 28, "15-28"), (age <= 56, "29-56"), else_="56+"
    )
    open_ = Complaint.status == "open"
    by_bucket: dict[str, int] = dict(
        db.execute(select(bucket, func.count()).where(open_).group_by(bucket)).all()
    )
    by_stage = dict(
        db.execute(select(Complaint.stage, func.count()).where(open_).group_by(Complaint.stage)).all()
    )
    overdue = dict(
        db.execute(
            select(Complaint.stage, func.count())
            .where(open_, Complaint.stage_due_at < now)
            .group_by(Complaint.stage)
        ).all()
    )
    closed_30 = db.execute(
        select(func.count()).where(Complaint.closed_at >= now - timedelta(days=30))
    ).scalar_one()
    reg_open = db.execute(select(func.count()).where(open_, Complaint.regulatory)).scalar_one()
    return {
        "buckets": [
            {"bucket": b, "count": by_bucket.get(b, 0)} for b in ("0-7", "8-14", "15-28", "29-56", "56+")
        ],
        "stages": [
            {
                "stage": s.key,
                "label": s.label,
                "open": by_stage.get(s.key, 0),
                "overdue": overdue.get(s.key, 0),
            }
            for s in [*WF.stages[:4], COMPLIANCE, WF.stages[4]]
        ],
        "open": sum(by_bucket.values()),
        "closed_last_30d": closed_30,
        "regulatory_open": reg_open,
    }
