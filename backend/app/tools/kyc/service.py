"""KYC rules. Every human decision is four-eyes via foundation.approvals; low-risk vendor-clean cases may be
auto-cleared by system:kyc-fastlane under versioned policy criteria."""

import random
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, policy
from app.foundation.audit import RETENTION_YEARS
from app.foundation.authz import Principal, system_principal
from app.foundation.datacls import mask_record
from app.foundation.db import utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid, NotFound, require_reason
from app.foundation.models import ApprovalRequest
from app.tools.kyc.models import OPEN_STATUSES, KycCase, KycDecision

CHAIN = "kyc"
RES = "kyc_case"
APPROVE_CODES = {"DOCS_VERIFIED", "RISK_ACCEPTABLE", "MANUAL_VERIFICATION"}
REJECT_CODES = {"ID_MISMATCH", "WATCHLIST_MATCH", "FRAUD_SUSPECTED", "INCOMPLETE_DOCS"}
PII_FIELDS = ("applicant_name", "email", "dob", "ssn", "address")
FASTLANE = "kyc-fastlane"


def scoped(q: Any, p: Principal) -> Any:
    """Row scope: users see only their region unless granted kyc.all_regions."""
    if p.has("kyc.all_regions") or p.is_system:
        return q
    return q.where(KycCase.region == (p.region or "__none__"))


def needs_senior(c: KycCase) -> bool:
    return c.requires_senior or c.risk_level == "high"


def sla_due(db: Session, risk: str, start: Any) -> Any:
    hours = policy.get(db, "kyc.sla_hours")[risk]
    return start + timedelta(hours=hours)


def get_case(db: Session, p: Principal, case_id: int, *, lock: bool = False) -> KycCase:
    q = scoped(select(KycCase).where(KycCase.id == case_id), p)
    if lock:
        q = q.with_for_update()
    c = db.execute(q).scalar_one_or_none()
    if c is None:
        raise NotFound("case not found")
    return c


def to_dict(c: KycCase) -> dict[str, Any]:
    now = utcnow()
    open_ = c.status in OPEN_STATUSES
    d = {
        "id": c.id,
        "ref": c.ref,
        "applicant_name": c.applicant_name,
        "email": c.email,
        "dob": c.dob,
        "ssn": c.ssn,
        "address": c.address,
        "country": c.country,
        "region": c.region,
        "risk_level": c.risk_level,
        "vendor_score": c.vendor_score,
        "watchlist_hits": c.watchlist_hits,
        "docs_verified": c.docs_verified,
        "status": c.status,
        "requires_senior": needs_senior(c),
        "assigned_to": c.assigned_to,
        "assigned_name": c.assigned_name,
        "recommendation": c.recommendation,
        "recommendation_code": c.recommendation_code,
        "decision": c.decision,
        "decision_code": c.decision_code,
        "decided_by": c.decided_by,
        "decided_at": c.decided_at.isoformat() if c.decided_at else None,
        "qa_status": c.qa_status,
        "sla_due_at": c.sla_due_at.isoformat(),
        "sla_breached": open_ and c.sla_due_at < now,
        "created_at": c.created_at.isoformat(),
    }
    return mask_record(RES, d)


def _touch(c: KycCase, p: Principal) -> None:
    if p.oid not in (c.touched_by or []):
        c.touched_by = [*(c.touched_by or []), p.oid]


def claim(db: Session, p: Principal, case_id: int) -> KycCase:
    c = get_case(db, p, case_id, lock=True)
    if c.status not in ("new", "info_requested"):
        raise Conflict(f"case is {c.status}; only new or info-requested cases can be claimed")
    if c.assigned_to and c.assigned_to != p.oid:
        raise Conflict(f"already claimed by {c.assigned_name}", code="already_claimed")
    if needs_senior(c) and not p.has("kyc.decide_high"):
        raise Forbidden("high-risk / escalated cases are worked by senior reviewers")
    c.assigned_to, c.assigned_name = p.oid, p.name
    if c.status == "new":
        c.status = "in_review"
    _touch(c, p)
    audit.record(db, p, "kyc.claimed", RES, c.id, chain=CHAIN, after={"assigned_to": p.oid})
    return c


def release(db: Session, p: Principal, case_id: int, reason: str | None) -> KycCase:
    reason = require_reason(reason)
    c = get_case(db, p, case_id, lock=True)
    _require_owner(c, p)
    c.assigned_to = c.assigned_name = None
    c.status = "new"
    audit.record(db, p, "kyc.released", RES, c.id, chain=CHAIN, reason=reason)
    return c


def _require_owner(c: KycCase, p: Principal) -> None:
    if c.assigned_to != p.oid:
        raise Forbidden("claim the case first")
    if c.status not in ("in_review", "info_requested"):
        raise Conflict(f"case is {c.status}")


def recommend(
    db: Session, p: Principal, case_id: int, decision: str, code: str, reason: str | None
) -> KycCase:
    reason = require_reason(reason, "a recommendation")
    if decision not in ("approve", "reject"):
        raise Invalid("decision must be approve or reject")
    if code not in (APPROVE_CODES if decision == "approve" else REJECT_CODES):
        raise Invalid(f"reason code {code} is not valid for {decision}")
    c = get_case(db, p, case_id, lock=True)
    _require_owner(c, p)
    if c.status != "in_review":
        raise Conflict("case is waiting for information")
    senior = needs_senior(c)
    c.recommendation, c.recommendation_code, c.recommended_by = decision, code, p.oid
    c.status = "pending_decision"
    c.assigned_to = c.assigned_name = None
    _touch(c, p)
    approvals.create_request(
        db,
        p,
        kind="kyc.decision",
        subject_type=RES,
        subject_id=c.id,
        title=f"KYC {c.ref}: {decision} ({code}){' — senior review' if senior else ''}",
        reason=reason,
        chain=CHAIN,
        requirement=approvals.Requirement(
            stages=[
                approvals.Stage(
                    "Senior reviewer" if senior else "Second reviewer",
                    "kyc.decide_high" if senior else "kyc.decide",
                )
            ],
            excluded_users=list(c.touched_by),
            note="Four-eyes: nobody who prepared this case may decide it.",
        ),
        payload={"case_id": c.id, "decision": decision, "code": code},
    )
    audit.record(
        db,
        p,
        "kyc.recommended",
        RES,
        c.id,
        chain=CHAIN,
        reason=reason,
        after={"recommendation": decision, "code": code},
    )
    return c


def _write_decision(
    db: Session,
    c: KycCase,
    *,
    decision: str,
    code: str,
    reason: str,
    by: str,
    by_name: str,
    approval_id: int | None,
) -> None:
    now = utcnow()
    c.decision, c.decision_code, c.decided_by, c.decided_at = decision, code, by, now
    db.add(
        KycDecision(
            case_id=c.id,
            decision=decision,
            reason_code=code,
            reason=reason,
            recommended_by=c.recommended_by,
            decided_by=by,
            decided_by_name=by_name,
            approval_request_id=approval_id,
            policy_version=policy.current_version(db, "kyc.fastlane_criteria")
            if code == "AUTO_CLEAR"
            else None,
            decided_at=now,
            retain_until=now + timedelta(days=365 * RETENTION_YEARS["kyc_decision"]),
        )
    )


def can_view_decision(db: Session, req: ApprovalRequest, p: Principal) -> bool:
    q = scoped(select(KycCase.id).where(KycCase.id == int(req.payload["case_id"])), p)
    return db.execute(q).scalar_one_or_none() is not None


def on_decision_approved(db: Session, req: ApprovalRequest) -> None:
    c = db.execute(select(KycCase).where(KycCase.id == req.payload["case_id"]).with_for_update()).scalar_one()
    last = approvals.decisions_for(db, req.id)[-1]
    c.status = "approved" if req.payload["decision"] == "approve" else "rejected"
    _write_decision(
        db,
        c,
        decision=req.payload["decision"],
        code=req.payload["code"],
        reason=last.reason,
        by=last.decided_by,
        by_name=last.decided_by_name,
        approval_id=req.id,
    )
    audit.record(
        db,
        system_principal("kyc"),
        "kyc.decided",
        RES,
        c.id,
        chain=CHAIN,
        reason=f"approval #{req.id} by {last.decided_by_name or last.decided_by}: {last.reason}",
        after={"status": c.status, "code": c.decision_code, "decided_by": last.decided_by},
        retention_class="kyc_decision",
    )


def on_decision_returned(db: Session, req: ApprovalRequest) -> None:
    c = db.execute(select(KycCase).where(KycCase.id == req.payload["case_id"]).with_for_update()).scalar_one()
    c.status = "in_review"
    c.assigned_to = c.recommended_by
    c.assigned_name = req.requested_by_name
    c.recommendation = c.recommendation_code = None
    audit.record(
        db,
        system_principal("kyc"),
        "kyc.recommendation_returned",
        RES,
        c.id,
        chain=CHAIN,
        reason=f"approval #{req.id} rejected",
    )


def request_info(db: Session, p: Principal, case_id: int, reason: str | None) -> KycCase:
    reason = require_reason(reason)
    c = get_case(db, p, case_id, lock=True)
    _require_owner(c, p)
    c.status = "info_requested"
    audit.record(db, p, "kyc.info_requested", RES, c.id, chain=CHAIN, reason=reason)
    return c


def info_received(db: Session, p: Principal, case_id: int, reason: str | None) -> KycCase:
    reason = require_reason(reason)
    c = get_case(db, p, case_id, lock=True)
    _require_owner(c, p)
    if c.status != "info_requested":
        raise Conflict("case is not waiting for information")
    c.status = "in_review"
    c.sla_due_at = sla_due(db, c.risk_level, utcnow())
    audit.record(
        db,
        p,
        "kyc.info_received",
        RES,
        c.id,
        chain=CHAIN,
        reason=reason,
        after={"sla_due_at": c.sla_due_at.isoformat()},
    )
    return c


def escalate(db: Session, p: Principal, case_id: int, reason: str | None) -> KycCase:
    reason = require_reason(reason, "an escalation")
    c = get_case(db, p, case_id, lock=True)
    _require_owner(c, p)
    c.requires_senior = True
    c.status = "new"
    c.assigned_to = c.assigned_name = None
    audit.record(
        db, p, "kyc.escalated", RES, c.id, chain=CHAIN, reason=reason, after={"requires_senior": True}
    )
    return c


def reveal(db: Session, p: Principal, case_id: int, field: str, reason: str | None) -> str:
    reason = require_reason(reason, "revealing PII")
    if field not in PII_FIELDS:
        raise Invalid("not a revealable field")
    c = get_case(db, p, case_id)
    audit.record(
        db,
        p,
        "kyc.pii_revealed",
        RES,
        c.id,
        chain=CHAIN,
        reason=reason,
        after={"field": field},
        retention_class="kyc_decision",
    )
    return str(getattr(c, field))


def fastlane_filter(criteria: dict[str, Any]) -> Any:
    conds = [
        KycCase.status == "new",
        KycCase.assigned_to.is_(None),
        KycCase.requires_senior.is_(False),
        KycCase.risk_level == "low",
        KycCase.vendor_score <= int(criteria["max_vendor_score"]),
        KycCase.watchlist_hits <= int(criteria["max_watchlist_hits"]),
    ]
    if criteria.get("require_docs_verified", True):
        conds.append(KycCase.docs_verified.is_(True))
    return and_(*conds)


def run_fastlane(db: Session, payload: dict[str, Any]) -> None:
    criteria = policy.get(db, "kyc.fastlane_criteria")
    version = policy.current_version(db, "kyc.fastlane_criteria")
    rate = float(policy.get(db, "kyc.qa_sample_rate"))
    rng = random.Random(payload.get("seed"))
    actor = system_principal(FASTLANE)
    cases = (
        db.execute(
            select(KycCase)
            .where(fastlane_filter(criteria))
            .order_by(KycCase.id)
            .limit(int(payload.get("limit", 2000)))
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    for c in cases:
        c.status = "auto_cleared"
        c.qa_status = "pending" if rng.random() < rate else None
        _write_decision(
            db,
            c,
            decision="approve",
            code="AUTO_CLEAR",
            reason=f"criteria v{version}: {criteria}",
            by=actor.oid,
            by_name=actor.name,
            approval_id=None,
        )
        audit.record(
            db,
            actor,
            "kyc.auto_cleared",
            RES,
            c.id,
            chain=CHAIN,
            reason="AUTO_CLEAR",
            after={
                "criteria_version": version,
                "vendor_score": c.vendor_score,
                "qa_sampled": c.qa_status == "pending",
            },
            retention_class="kyc_decision",
        )


def qa_review(db: Session, p: Principal, case_id: int, result: str, reason: str | None) -> KycCase:
    reason = require_reason(reason)
    if result not in ("passed", "failed"):
        raise Invalid("result must be passed or failed")
    c = get_case(db, p, case_id, lock=True)
    if c.qa_status != "pending":
        raise Conflict("case is not in the QA sample")
    c.qa_status = result
    if result == "failed":
        c.status, c.requires_senior = "new", True
        c.decision = c.decision_code = None
    audit.record(
        db,
        p,
        "kyc.qa_reviewed",
        RES,
        c.id,
        chain=CHAIN,
        reason=reason,
        after={"qa_status": result},
        retention_class="kyc_decision",
    )
    return c


def stats(db: Session, p: Principal) -> dict[str, Any]:
    q = scoped(select(KycCase.status, func.count()).group_by(KycCase.status), p)
    counts = {s: n for s, n in db.execute(q).all()}
    breached = db.execute(
        scoped(
            select(func.count())
            .select_from(KycCase)
            .where(KycCase.status.in_(OPEN_STATUSES), KycCase.sla_due_at < utcnow()),
            p,
        )
    ).scalar_one()
    return {"counts": counts, "sla_breached": breached}
