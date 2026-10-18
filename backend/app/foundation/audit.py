"""Append-only, hash-chained audit log.

`record()` runs inside the caller's transaction, so the audit row commits or rolls back with the
business change. The app DB role cannot UPDATE/DELETE audit rows (grants + trigger, see migration).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.foundation.authz import Principal
from app.foundation.datacls import fingerprint_record
from app.foundation.models import AuditEvent
from app.foundation.request_context import current_request_id

GENESIS = "0" * 64

RETENTION_YEARS = {
    "kyc_decision": 5,  # brief: KYC decision records retained 5 years
    "financial": 7,  # assumption: refunds/AP follow typical 7-year finance retention (confirm with customer)
    "standard": 3,  # assumption
}


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def _hash_fields(e: AuditEvent) -> dict[str, Any]:
    return {
        "chain": e.chain,
        "occurred_at": e.occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor_id": e.actor_id,
        "actor_roles": sorted(e.actor_roles),
        "action": e.action,
        "resource": e.resource,
        "resource_id": e.resource_id,
        "reason": e.reason,
        "before": e.before,
        "after": e.after,
        "retention_class": e.retention_class,
        "retain_until": e.retain_until.astimezone(UTC).isoformat(timespec="microseconds"),
    }


def compute_hash(prev_hash: str, e: AuditEvent) -> str:
    return hashlib.sha256((prev_hash + _canon(_hash_fields(e))).encode()).hexdigest()


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Keep only changed keys."""
    if before is None or after is None:
        return before, after
    keys = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return {k: before.get(k) for k in sorted(keys)}, {k: after.get(k) for k in sorted(keys)}


def record(
    db: Session,
    actor: Principal,
    action: str,
    resource: str,
    resource_id: Any,
    *,
    chain: str,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    retention_class: str = "standard",
) -> AuditEvent:
    b, a = diff(before, after)
    if b is not None:
        b = fingerprint_record(resource, b)
    if a is not None:
        a = fingerprint_record(resource, a)
    now = datetime.now(UTC)
    # Serialize writers per chain; the lock is released when the business transaction ends.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:c))"), {"c": "audit:" + chain})
    prev = db.execute(
        select(AuditEvent.hash).where(AuditEvent.chain == chain).order_by(AuditEvent.seq.desc()).limit(1)
    ).scalar_one_or_none()
    e = AuditEvent(
        chain=chain,
        occurred_at=now,
        actor_id=actor.oid,
        actor_name=actor.name,
        actor_roles=sorted(actor.roles),
        action=action,
        resource=resource,
        resource_id=str(resource_id),
        reason=reason,
        before=b,
        after=a,
        request_id=current_request_id(),
        retention_class=retention_class,
        retain_until=now + timedelta(days=365 * RETENTION_YEARS[retention_class] + RETENTION_YEARS[retention_class] // 4),
        prev_hash=prev or GENESIS,
        hash="",
    )
    e.hash = compute_hash(e.prev_hash, e)
    db.add(e)
    db.flush()
    return e


@dataclass
class VerifyResult:
    chain: str
    count: int
    ok: bool
    first_bad_seq: int | None = None
    problem: str | None = None
    head: str | None = None


def verify_chain(db: Session, chain: str) -> VerifyResult:
    prev = GENESIS
    n = 0
    rows = db.execute(select(AuditEvent).where(AuditEvent.chain == chain).order_by(AuditEvent.seq)).scalars()
    for e in rows:
        n += 1
        if e.prev_hash != prev:
            return VerifyResult(chain, n, False, e.seq, "prev_hash does not match previous event (row removed or reordered)")
        if compute_hash(prev, e) != e.hash:
            return VerifyResult(chain, n, False, e.seq, "content hash mismatch (row modified)")
        prev = e.hash
    return VerifyResult(chain, n, True, head=prev)


def chains(db: Session) -> list[str]:
    return list(db.execute(select(AuditEvent.chain).distinct().order_by(AuditEvent.chain)).scalars())


def to_dict(e: AuditEvent) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "chain": e.chain,
        "occurred_at": e.occurred_at.isoformat(),
        "actor_id": e.actor_id,
        "actor_name": e.actor_name,
        "actor_roles": e.actor_roles,
        "action": e.action,
        "resource": e.resource,
        "resource_id": e.resource_id,
        "reason": e.reason,
        "before": e.before,
        "after": e.after,
        "request_id": e.request_id,
        "retention_class": e.retention_class,
        "retain_until": e.retain_until.isoformat(),
        "prev_hash": e.prev_hash,
        "hash": e.hash,
    }
