"""Policy-as-data: thresholds and windows are versioned rows; changing one needs an approval."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit
from app.foundation.authz import Principal, system_principal
from app.foundation.errors import Conflict, Invalid, NotFound
from app.foundation.models import ApprovalRequest, PolicyValue
from app.foundation.registry import PolicyDef, get_registry


def _def(key: str) -> PolicyDef:
    d = get_registry().policies.get(key)
    if d is None:
        raise NotFound(f"unknown policy {key!r}")
    return d


def get(db: Session, key: str) -> Any:
    row = db.execute(
        select(PolicyValue).where(PolicyValue.key == key).order_by(PolicyValue.version.desc()).limit(1)
    ).scalar_one_or_none()
    return row.value if row else _def(key).default


def current_version(db: Session, key: str) -> int:
    return db.execute(
        select(func.coalesce(func.max(PolicyValue.version), 0)).where(PolicyValue.key == key)
    ).scalar_one()


def validate(key: str, value: Any) -> Any:
    d = _def(key)
    if d.kind in ("int", "cents"):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise Invalid(f"{key} must be a non-negative integer")
    elif d.kind == "float":
        if not isinstance(value, int | float) or not 0 <= float(value) <= 1:
            raise Invalid(f"{key} must be between 0 and 1")
        value = float(value)
    return value


def request_change(db: Session, actor: Principal, key: str, value: Any, reason: str) -> ApprovalRequest:
    value = validate(key, value)
    if approvals.open_for_subject(db, "policy", key):
        raise Conflict("a change to this policy is already awaiting approval")
    old = get(db, key)
    return approvals.create_request(
        db,
        actor,
        kind="core.policy_change",
        subject_type="policy",
        subject_id=key,
        title=f"Change policy {key}: {old!r} → {value!r}",
        reason=reason,
        chain="core",
        requirement=approvals.Requirement(
            stages=[approvals.Stage("Policy approver", "core.policy.approve")], excluded_users=[actor.oid]
        ),
        payload={"key": key, "old": old, "new": value, "base_version": current_version(db, key)},
    )


def apply_approved(db: Session, req: ApprovalRequest) -> None:
    key = req.payload["key"]
    if current_version(db, key) != req.payload["base_version"]:
        raise Conflict("policy changed since this request was made; request again")
    v = PolicyValue(
        key=key,
        version=req.payload["base_version"] + 1,
        value=req.payload["new"],
        created_by=req.requested_by,
        approval_request_id=req.id,
    )
    db.add(v)
    audit.record(
        db,
        system_principal("policy"),
        "policy.changed",
        "policy",
        key,
        chain="core",
        reason=f"approval #{req.id}",
        before={"value": req.payload["old"]},
        after={"value": req.payload["new"]},
    )


def seed_defaults(db: Session) -> None:
    for key, d in get_registry().policies.items():
        if current_version(db, key) == 0:
            db.add(PolicyValue(key=key, version=1, value=d.default, created_by="system:seed"))


def list_all(db: Session) -> list[dict[str, Any]]:
    out = []
    for key, d in sorted(get_registry().policies.items()):
        pending = approvals.open_for_subject(db, "policy", key)
        out.append(
            {
                "key": key,
                "description": d.description,
                "kind": d.kind,
                "value": get(db, key),
                "version": current_version(db, key),
                "pending_request_id": pending.id if pending else None,
            }
        )
    return out
