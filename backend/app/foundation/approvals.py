"""Reusable maker-checker approvals.

Invariants (property-tested in tests/test_approvals_props.py):
- the requester never approves their own request;
- excluded users (e.g. anyone who prepared a KYC case) never decide;
- one person decides at most once per request, so they can't satisfy two stages;
- every decision has a reason and is audited;
- deciding again with the same decision is idempotent; closed requests accept no decisions.
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.foundation import audit
from app.foundation.authz import Principal
from app.foundation.errors import Conflict, Forbidden, Invalid, NotFound, require_reason
from app.foundation.models import ApprovalDecision, ApprovalRequest
from app.foundation.registry import get_registry


@dataclass
class Stage:
    name: str
    permission: str
    min_approvers: int = 1


@dataclass
class Requirement:
    stages: list[Stage]
    excluded_users: list[str] = field(default_factory=list)
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_json(d: dict[str, Any]) -> "Requirement":
        return Requirement(stages=[Stage(**s) for s in d["stages"]], excluded_users=list(d.get("excluded_users", [])),
                           note=d.get("note", ""))


def create_request(
    db: Session,
    actor: Principal,
    *,
    kind: str,
    subject_type: str,
    subject_id: Any,
    title: str,
    reason: str,
    requirement: Requirement,
    chain: str,
    payload: dict[str, Any] | None = None,
) -> ApprovalRequest:
    if kind not in get_registry().approval_kinds:
        raise Invalid(f"unknown approval kind {kind!r}")
    if not requirement.stages:
        raise Invalid("an approval needs at least one stage")
    for st in requirement.stages:
        if st.permission not in get_registry().permissions:
            raise Invalid(f"unknown approver permission {st.permission!r}")
    reason = require_reason(reason, "an approval request")
    req = ApprovalRequest(
        kind=kind, subject_type=subject_type, subject_id=str(subject_id), title=title, requested_by=actor.oid,
        requested_by_name=actor.name, request_reason=reason, requirement=requirement.to_json(), payload=payload or {},
        status="open", current_stage=0,
    )
    db.add(req)
    db.flush()
    audit.record(db, actor, "approval.requested", "approval", req.id, chain=chain, reason=reason,
                 after={"kind": kind, "subject": f"{subject_type}:{subject_id}", "requirement": requirement.to_json()})
    return req


def can_decide(req: ApprovalRequest, actor: Principal) -> tuple[bool, str]:
    if req.status != "open":
        return False, "request is closed"
    if actor.oid == req.requested_by:
        return False, "you cannot approve your own request"
    reqm = Requirement.from_json(req.requirement)
    if actor.oid in reqm.excluded_users:
        return False, "you are excluded from deciding this request (separation of duties)"
    stage = reqm.stages[req.current_stage]
    if not actor.has(stage.permission):
        return False, f"stage '{stage.name}' requires {stage.permission}"
    return True, ""


def decide(
    db: Session,
    actor: Principal,
    request_id: int,
    decision: Literal["approve", "reject"],
    reason: str | None,
    *,
    chain: str | None = None,
) -> ApprovalRequest:
    if decision not in ("approve", "reject"):
        raise Invalid("decision must be approve or reject")
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()).scalar_one_or_none()
    if req is None:
        raise NotFound("approval request not found")
    prior = db.execute(
        select(ApprovalDecision).where(ApprovalDecision.request_id == req.id, ApprovalDecision.decided_by == actor.oid)
    ).scalar_one_or_none()
    if prior is not None:
        if prior.decision == decision:
            return req  # idempotent replay
        raise Conflict("you already decided this request differently")
    reason = require_reason(reason, "an approval decision")
    ok, why = can_decide(req, actor)
    if not ok:
        raise (Conflict(why) if req.status != "open" else Forbidden(why, code="sod_violation"))
    reqm = Requirement.from_json(req.requirement)
    db.add(ApprovalDecision(request_id=req.id, stage=req.current_stage, decided_by=actor.oid, decided_by_name=actor.name,
                            decision=decision, reason=reason))
    db.flush()
    chain = chain or req.kind.split(".")[0]
    before = {"status": req.status, "current_stage": req.current_stage}
    hooks = get_registry().approval_kinds[req.kind]
    if decision == "reject":
        req.status, req.closed_at = "rejected", datetime.now(UTC)
    else:
        approvals_here = db.execute(
            select(ApprovalDecision).where(ApprovalDecision.request_id == req.id,
                                           ApprovalDecision.stage == req.current_stage,
                                           ApprovalDecision.decision == "approve")
        ).scalars().all()
        if len(approvals_here) >= reqm.stages[req.current_stage].min_approvers:
            if req.current_stage + 1 >= len(reqm.stages):
                req.status, req.closed_at = "approved", datetime.now(UTC)
            else:
                req.current_stage += 1
    audit.record(db, actor, f"approval.{decision}", "approval", req.id, chain=chain, reason=reason, before=before,
                 after={"status": req.status, "current_stage": req.current_stage})
    db.flush()
    if req.status == "approved":
        hooks.on_approved(db, req)
    elif req.status == "rejected" and hooks.on_rejected:
        hooks.on_rejected(db, req)
    return req


def cancel(db: Session, actor: Principal, request_id: int, reason: str, *, chain: str) -> ApprovalRequest:
    req = db.execute(select(ApprovalRequest).where(ApprovalRequest.id == request_id).with_for_update()).scalar_one()
    if req.status != "open":
        raise Conflict("request is closed")
    if req.requested_by != actor.oid and not actor.is_system:
        raise Forbidden("only the requester can cancel")
    reason = require_reason(reason, "cancelling")
    req.status, req.closed_at = "cancelled", datetime.now(UTC)
    audit.record(db, actor, "approval.cancel", "approval", req.id, chain=chain, reason=reason, after={"status": "cancelled"})
    return req


def open_for_subject(db: Session, subject_type: str, subject_id: Any) -> ApprovalRequest | None:
    return db.execute(
        select(ApprovalRequest).where(ApprovalRequest.subject_type == subject_type,
                                      ApprovalRequest.subject_id == str(subject_id), ApprovalRequest.status == "open")
    ).scalar_one_or_none()


def to_dict(req: ApprovalRequest, decisions: list[ApprovalDecision], viewer: Principal | None = None) -> dict[str, Any]:
    reqm = Requirement.from_json(req.requirement)
    out = {
        "id": req.id, "kind": req.kind, "subject_type": req.subject_type, "subject_id": req.subject_id, "title": req.title,
        "requested_by": req.requested_by, "requested_by_name": req.requested_by_name, "request_reason": req.request_reason,
        "requested_at": req.requested_at.isoformat(), "status": req.status, "current_stage": req.current_stage,
        "stages": [asdict(s) for s in reqm.stages], "excluded_count": len(reqm.excluded_users), "note": reqm.note,
        "payload": req.payload,
        "decisions": [{"stage": d.stage, "decided_by_name": d.decided_by_name, "decision": d.decision, "reason": d.reason,
                       "decided_at": d.decided_at.isoformat()} for d in decisions],
    }
    if viewer is not None:
        ok, why = can_decide(req, viewer)
        out["can_decide"], out["cannot_decide_reason"] = ok, why
    return out


def decisions_for(db: Session, request_id: int) -> list[ApprovalDecision]:
    return list(db.execute(select(ApprovalDecision).where(ApprovalDecision.request_id == request_id)
                           .order_by(ApprovalDecision.id)).scalars())
