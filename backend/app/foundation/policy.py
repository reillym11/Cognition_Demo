"""Policy-as-data: thresholds and windows are versioned rows; changing one needs an approval."""

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit
from app.foundation.authz import Principal, system_principal
from app.foundation.errors import Conflict, Invalid, NotFound
from app.foundation.models import ApprovalRequest, PolicyValue
from app.foundation.registry import PolicyDef, get_registry

log = logging.getLogger("itp.policy")


def _def(key: str) -> PolicyDef:
    d = get_registry().policies.get(key)
    if d is None:
        raise NotFound(f"unknown policy {key!r}")
    return d


def get(db: Session, key: str) -> Any:
    """Current value. A stored value that fails validation is never used: the default applies and we alert."""
    d = _def(key)
    row = db.execute(
        select(PolicyValue).where(PolicyValue.key == key).order_by(PolicyValue.version.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None:
        return d.default
    try:
        return _check(key, d, row.value)
    except Invalid as e:
        log.error("policy %s v%s is invalid (%s); falling back to the default", key, row.version, e)
        return d.default


def current_version(db: Session, key: str) -> int:
    return db.execute(
        select(func.coalesce(func.max(PolicyValue.version), 0)).where(PolicyValue.key == key)
    ).scalar_one()


def validate(key: str, value: Any) -> Any:
    return _check(key, _def(key), value)


def _check(key: str, d: PolicyDef, value: Any) -> Any:
    if d.kind in ("int", "cents"):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise Invalid(f"{key} must be a non-negative integer")
    elif d.kind == "float":
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= float(value) <= 1:
            raise Invalid(f"{key} must be between 0 and 1")
        value = float(value)
    elif d.kind == "json" and d.schema is not None:
        try:
            value = d.schema.model_validate(value, strict=True).model_dump(mode="json")
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'value'}: {x['msg']}" for x in e.errors())
            raise Invalid(f"{key} is invalid: {problems}") from None
    else:
        raise Invalid(f"{key} has no validator for kind {d.kind!r}")
    return value


def request_change(db: Session, actor: Principal, key: str, value: Any, reason: str) -> ApprovalRequest:
    d = _def(key)
    value = _check(key, d, value)
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
            stages=[approvals.Stage("Policy approver", d.approver)], excluded_users=[actor.oid]
        ),
        payload={"key": key, "old": old, "new": value, "base_version": current_version(db, key)},
    )


def apply_approved(db: Session, req: ApprovalRequest) -> None:
    key = req.payload["key"]
    d = _def(key)
    stages = approvals.Requirement.from_json(req.requirement).stages
    if [s.permission for s in stages] != [d.approver]:
        raise Conflict(f"this policy now needs {d.approver} to approve; request again")
    new = _check(key, d, req.payload["new"])
    if current_version(db, key) != req.payload["base_version"]:
        raise Conflict("policy changed since this request was made; request again")
    v = PolicyValue(
        key=key,
        version=req.payload["base_version"] + 1,
        value=new,
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
        after={"value": new},
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
                "approver": d.approver,
                "value": get(db, key),
                "version": current_version(db, key),
                "pending_request_id": pending.id if pending else None,
            }
        )
    return out
