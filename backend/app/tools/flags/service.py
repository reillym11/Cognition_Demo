"""Thin feature flags: per-env state, % rollout with deterministic bucketing, simple targeting rules,
explicit missing-flag defaults, prod changes behind a second person, full change history, stale detection."""

import hashlib
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, notify
from app.foundation.authz import Principal, system_principal
from app.foundation.db import utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid, NotFound, require_reason
from app.foundation.models import ApprovalDecision, ApprovalRequest
from app.tools.flags.models import ENVS, Flag, FlagChange, FlagEnv

CHAIN = "flags"
RES = "flag"
KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")
ATTRS = {"user_id", "region", "plan", "email_domain"}
OPS = {"in", "not_in"}
STALE_DAYS = 14
CONFIG_FIELDS = ("enabled", "rollout_pct", "rules", "default_value")


def bucket(flag_key: str, user_id: str) -> int:
    """Stable 0..9999 bucket: same user + flag always lands in the same place, independent per flag."""
    return int(hashlib.sha256(f"{flag_key}:{user_id}".encode()).hexdigest()[:8], 16) % 10_000


def validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    pct = cfg.get("rollout_pct")
    if isinstance(pct, bool) or not isinstance(pct, int) or not 0 <= pct <= 100:
        raise Invalid("rollout_pct must be an integer 0..100")
    rules = cfg.get("rules") or []
    if not isinstance(rules, list) or len(rules) > 10:
        raise Invalid("rules must be a list of at most 10 rules")
    clean = []
    for r in rules:
        if not isinstance(r, dict) or r.get("attribute") not in ATTRS or r.get("op") not in OPS:
            raise Invalid(f"each rule needs attribute in {sorted(ATTRS)} and op in {sorted(OPS)}")
        vals = r.get("values")
        if (
            not isinstance(vals, list)
            or not vals
            or len(vals) > 50
            or not all(isinstance(v, str) for v in vals)
        ):
            raise Invalid("rule values must be a non-empty list of up to 50 strings")
        clean.append({"attribute": r["attribute"], "op": r["op"], "values": vals})
    return {
        "enabled": bool(cfg.get("enabled")),
        "rollout_pct": pct,
        "rules": clean,
        "default_value": bool(cfg.get("default_value")),
    }


def config_of(e: FlagEnv) -> dict[str, Any]:
    return {f: getattr(e, f) for f in CONFIG_FIELDS}


def is_stale(e: FlagEnv) -> bool:
    return bool(
        e.env == "prod"
        and e.full_rollout_since is not None
        and e.full_rollout_since < utcnow() - timedelta(days=STALE_DAYS)
    )


def _matches(rule: dict[str, Any], ctx: dict[str, str]) -> bool:
    v = ctx.get(rule["attribute"])
    hit = v is not None and v in rule["values"]
    return hit if rule["op"] == "in" else not hit


def evaluate(db: Session, key: str, env: str, ctx: dict[str, str], default: bool) -> dict[str, Any]:
    if env not in ENVS:
        raise Invalid(f"env must be one of {ENVS}")
    row = db.execute(
        select(FlagEnv).join(Flag).where(Flag.key == key, FlagEnv.env == env)
    ).scalar_one_or_none()
    if row is None:
        return {"value": default, "reason": "FLAG_NOT_FOUND"}
    if not row.enabled:
        return {"value": row.default_value, "reason": "DISABLED", "version": row.version}
    if not all(_matches(r, ctx) for r in row.rules):
        return {"value": row.default_value, "reason": "RULE_MISS", "version": row.version}
    uid = ctx.get("user_id")
    if row.rollout_pct >= 100:
        return {"value": True, "reason": "FULL_ROLLOUT", "version": row.version}
    if not uid:
        return {"value": row.default_value, "reason": "NO_USER_ID", "version": row.version}
    inside = bucket(key, uid) < row.rollout_pct * 100
    return {
        "value": inside or row.default_value,
        "reason": "ROLLOUT_IN" if inside else "ROLLOUT_OUT",
        "version": row.version,
    }


def get_flag(db: Session, key: str) -> Flag:
    f = db.execute(select(Flag).where(Flag.key == key)).scalar_one_or_none()
    if f is None:
        raise NotFound("flag not found")
    return f


def envs_for(db: Session, flag_id: int, *, lock: bool = False) -> dict[str, FlagEnv]:
    q = select(FlagEnv).where(FlagEnv.flag_id == flag_id)
    if lock:
        q = q.with_for_update()
    return {e.env: e for e in db.execute(q).scalars()}


def create_flag(
    db: Session, p: Principal, key: str, description: str, owner: str, reason: str | None
) -> Flag:
    reason = require_reason(reason, "creating a flag")
    if not KEY_RE.match(key):
        raise Invalid("key must be 3-64 chars: lowercase letters, digits, . _ -; starting with a letter")
    if db.execute(select(Flag.id).where(Flag.key == key)).first():
        raise Conflict("a flag with this key exists")
    f = Flag(key=key, description=description.strip(), owner=owner.strip() or p.name, created_by=p.oid)
    db.add(f)
    db.flush()
    for env in ENVS:
        db.add(
            FlagEnv(
                flag_id=f.id,
                env=env,
                enabled=False,
                rollout_pct=0,
                rules=[],
                default_value=False,
                updated_by=p.name,
            )
        )
    audit.record(
        db, p, "flag.created", RES, f.key, chain=CHAIN, reason=reason, after={"key": key, "owner": f.owner}
    )
    return f


def _apply(
    db: Session,
    f: Flag,
    e: FlagEnv,
    cfg: dict[str, Any],
    actor: Principal,
    *,
    by_name: str,
    by_oid: str,
    reason: str,
    approved_by: str | None = None,
    approval_id: int | None = None,
) -> None:
    before = config_of(e)
    if before == cfg:
        raise Invalid("no change")
    for k, v in cfg.items():
        setattr(e, k, v)
    full = cfg["enabled"] and cfg["rollout_pct"] == 100 and not cfg["rules"]
    if full and e.full_rollout_since is None:
        e.full_rollout_since = utcnow()
    elif not full:
        e.full_rollout_since = None
    e.version += 1
    e.updated_by, e.updated_at = by_name, utcnow()
    db.add(
        FlagChange(
            flag_id=f.id,
            env=e.env,
            actor=by_oid,
            actor_name=by_name,
            approved_by=approved_by,
            reason=reason,
            before=before,
            after=cfg,
            approval_request_id=approval_id,
        )
    )
    audit.record(
        db,
        actor,
        "flag.changed",
        RES,
        f.key,
        chain=CHAIN,
        reason=reason,
        before={"env": e.env, **before},
        after={"env": e.env, **cfg},
    )


def change(
    db: Session, p: Principal, key: str, env: str, raw: dict[str, Any], reason: str | None
) -> dict[str, Any]:
    reason = require_reason(reason, "a flag change")
    if env not in ENVS:
        raise Invalid(f"env must be one of {ENVS}")
    cfg = validate_config(raw)
    f = get_flag(db, key)
    e = envs_for(db, f.id, lock=True)[env]
    if env != "prod":
        _apply(db, f, e, cfg, p, by_name=p.name, by_oid=p.oid, reason=reason)
        return {"status": "applied", "version": e.version}
    if not p.has("flags.prod.request"):
        raise Forbidden("missing permission flags.prod.request")
    if approvals.open_for_subject(db, RES, f"{f.key}:prod"):
        raise Conflict("a production change for this flag is already awaiting approval")
    if config_of(e) == cfg:
        raise Invalid("no change")
    req = approvals.create_request(
        db,
        p,
        kind="flags.prod_change",
        subject_type=RES,
        subject_id=f"{f.key}:prod",
        title=f"Prod change: {f.key}",
        reason=reason,
        requirement=approvals.Requirement(
            stages=[approvals.Stage("Platform admin", "flags.prod.approve")],
            excluded_users=[p.oid],
            note="Production flag changes need a second person",
        ),
        chain=CHAIN,
        payload={"flag_key": f.key, "before": config_of(e), "after": cfg, "base_version": e.version},
    )
    return {"status": "pending_approval", "approval_request_id": req.id}


def on_prod_approved(db: Session, req: ApprovalRequest) -> None:
    f = get_flag(db, req.payload["flag_key"])
    e = envs_for(db, f.id, lock=True)["prod"]
    if e.version != req.payload["base_version"]:
        raise Conflict("prod config changed since this request was made; ask for a fresh approval")
    approver = (
        db.execute(
            select(ApprovalDecision.decided_by_name)
            .where(ApprovalDecision.request_id == req.id)
            .order_by(ApprovalDecision.id.desc())
        )
        .scalars()
        .first()
    )
    _apply(
        db,
        f,
        e,
        req.payload["after"],
        system_principal("flags-approval"),
        by_name=req.requested_by_name,
        by_oid=req.requested_by,
        reason=req.request_reason,
        approved_by=approver,
        approval_id=req.id,
    )


def history(db: Session, flag_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(FlagChange).where(FlagChange.flag_id == flag_id).order_by(FlagChange.id.desc())
    ).scalars()
    return [
        {
            "id": c.id,
            "env": c.env,
            "actor": c.actor_name,
            "approved_by": c.approved_by,
            "reason": c.reason,
            "before": c.before,
            "after": c.after,
            "approval_request_id": c.approval_request_id,
            "at": c.created_at.isoformat(),
        }
        for c in rows
    ]


def flag_dict(f: Flag, envs: dict[str, FlagEnv]) -> dict[str, Any]:
    return {
        "id": f.id,
        "key": f.key,
        "description": f.description,
        "owner": f.owner,
        "created_at": f.created_at.isoformat(),
        "envs": {
            k: {
                **config_of(e),
                "version": e.version,
                "updated_by": e.updated_by,
                "updated_at": e.updated_at.isoformat(),
                "full_rollout_since": e.full_rollout_since.isoformat() if e.full_rollout_since else None,
                "stale": is_stale(e),
            }
            for k, e in envs.items()
        },
        "stale": any(is_stale(e) for e in envs.values()),
    }


def stale_flags(db: Session) -> list[dict[str, Any]]:
    cutoff = utcnow() - timedelta(days=STALE_DAYS)
    rows = db.execute(
        select(Flag, FlagEnv)
        .join(FlagEnv)
        .where(FlagEnv.env == "prod", FlagEnv.full_rollout_since < cutoff)
        .order_by(FlagEnv.full_rollout_since)
    ).all()
    return [
        {
            "key": f.key,
            "owner": f.owner,
            "full_rollout_since": e.full_rollout_since.isoformat() if e.full_rollout_since else None,
            "days": (utcnow() - e.full_rollout_since).days if e.full_rollout_since else 0,
        }
        for f, e in rows
    ]


def stale_report(db: Session, _: dict[str, Any]) -> None:
    stale = stale_flags(db)
    if stale:
        notify.teams(
            db,
            "flag-hygiene",
            f"{len(stale)} flags at 100% in prod for over {STALE_DAYS} days",
            {s["key"]: f"{s['days']} days, owner {s['owner']}" for s in stale[:15]},
            link="/flags?stale=1",
        )
