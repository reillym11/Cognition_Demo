"""Refund rules: integer cents, cumulative reservation under a row lock, policy threshold with a different
approver, velocity flag, idempotent execution, and reconciliation of unknown processor outcomes."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, jobs, notify, policy
from app.foundation.authz import Principal, system_principal
from app.foundation.datacls import mask_record
from app.foundation.db import utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid, NotFound, require_reason
from app.foundation.models import ApprovalRequest
from app.foundation.money import Money
from app.tools.refunds.models import RESERVING, Refund, Transaction
from app.tools.refunds.processor import ProcessorRejected, ProcessorUnknown, get_processor

CHAIN = "refunds"
RES = "refund"
TXN = "refund_transaction"
REASON_CODES = {"DUPLICATE_CHARGE", "NOT_RECEIVED", "SERVICE_ISSUE", "GOODWILL", "FRAUD_CLAIM"}
PII_FIELDS = ("customer_name", "customer_email")


def fmt(cents: int, currency: str = "USD") -> str:
    return Money(int(cents), currency).format()


def scoped(q: Any, p: Principal) -> Any:
    """Row scope: users see only their merchants' region unless granted refunds.all_regions.
    `q` must select from (or join) Transaction."""
    if p.has("refunds.all_regions") or p.is_system:
        return q
    return q.where(Transaction.region == (p.region or "__none__"))


def get_txn(db: Session, p: Principal, txn_id: int, *, lock: bool = False) -> Transaction:
    q = scoped(select(Transaction).where(Transaction.id == txn_id), p)
    if lock:
        q = q.with_for_update()
    t = db.execute(q).scalar_one_or_none()
    if t is None:
        raise NotFound("transaction not found")
    return t


def get_refund(db: Session, p: Principal, refund_id: int, *, lock: bool = False) -> Refund:
    q = scoped(select(Refund).join(Transaction).where(Refund.id == refund_id), p)
    if lock:
        q = q.with_for_update(of=Refund)
    r = db.execute(q).scalar_one_or_none()
    if r is None:
        raise NotFound("refund not found")
    return r


def lock_requester(db: Session, oid: str) -> None:
    """Serialise one requester's refund requests so the velocity count sees their other in-flight requests,
    whichever charges those are against. Two-key form keeps it out of audit's single-key lock space."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('refunds.velocity'), hashtext(:oid))"), {"oid": oid}
    )


def reserved_cents(db: Session, txn_id: int) -> int:
    return int(
        db.execute(
            select(func.coalesce(func.sum(Refund.amount_cents), 0)).where(
                Refund.transaction_id == txn_id, Refund.status.in_(RESERVING)
            )
        ).scalar_one()
    )


def txn_dict(t: Transaction, reserved: int | None = None) -> dict[str, Any]:
    d = {
        "id": t.id,
        "charge_id": t.charge_id,
        "merchant": t.merchant,
        "region": t.region,
        "customer_name": t.customer_name,
        "customer_email": t.customer_email,
        "card_last4": t.card_last4,
        "amount_cents": t.amount_cents,
        "currency": t.currency,
        "amount": fmt(t.amount_cents, t.currency),
        "captured_at": t.captured_at.isoformat(),
    }
    if reserved is not None:
        d |= {"reserved_cents": reserved, "remaining_cents": t.amount_cents - reserved}
    return mask_record(TXN, d)


def refund_dict(r: Refund, t: Transaction | None = None) -> dict[str, Any]:
    d = {
        "id": r.id,
        "transaction_id": r.transaction_id,
        "amount_cents": r.amount_cents,
        "currency": r.currency,
        "amount": fmt(r.amount_cents, r.currency),
        "status": r.status,
        "reason_code": r.reason_code,
        "reason": r.reason,
        "requested_by": r.requested_by,
        "requested_by_name": r.requested_by_name,
        "processor_ref": r.processor_ref,
        "approval_request_id": r.approval_request_id,
        "needs_approval": r.needs_approval,
        "approval_why": r.approval_why,
        "velocity_flag": r.velocity_flag,
        "attempts": r.attempts,
        "last_error": r.last_error,
        "created_at": r.created_at.isoformat(),
        "executed_at": r.executed_at.isoformat() if r.executed_at else None,
    }
    if t is not None:
        d |= {"charge_id": t.charge_id, "merchant": t.merchant, "region": t.region}
    return d


def request_refund(
    db: Session, p: Principal, txn_id: int, amount_cents: int, reason_code: str, reason: str | None
) -> Refund:
    reason = require_reason(reason, "a refund request")
    if reason_code not in REASON_CODES:
        raise Invalid(f"reason_code must be one of {sorted(REASON_CODES)}", code="reason_code")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0:
        raise Invalid("amount_cents must be a positive integer number of cents")
    lock_requester(db, p.oid)
    t = get_txn(db, p, txn_id, lock=True)  # serialises concurrent refunds on the same charge
    amount = Money(amount_cents, t.currency)
    reserved = reserved_cents(db, t.id)
    remaining = t.amount_cents - reserved
    if amount_cents > remaining:
        raise Conflict(
            f"refund of {amount.format()} exceeds the refundable balance {fmt(remaining, t.currency)}",
            code="over_refund",
        )
    threshold = int(policy.get(db, "refunds.approval_threshold_cents"))
    vel = policy.get(db, "refunds.velocity")
    recent = db.execute(
        select(func.count())
        .select_from(Refund)
        .where(
            Refund.requested_by == p.oid,
            Refund.created_at > utcnow() - timedelta(minutes=int(vel["window_minutes"])),
        )
    ).scalar_one()
    velocity_flag = recent >= int(vel["max_requests"])
    why = []
    if reserved + amount_cents > threshold:
        why.append(f"cumulative refunds on this charge exceed {fmt(threshold)}")
    if velocity_flag:
        why.append(f"requester made {recent} refund requests in {vel['window_minutes']} min")
    if not p.has("refunds.request.direct"):
        why.append("requester's role always needs a second person")
    r = Refund(
        transaction_id=t.id,
        amount_cents=amount_cents,
        currency=t.currency,
        status="pending_approval" if why else "approved",
        reason_code=reason_code,
        reason=reason,
        requested_by=p.oid,
        requested_by_name=p.name,
        idempotency_key=f"rf_{uuid4().hex}",
        needs_approval=bool(why),
        approval_why="; ".join(why) or None,
        velocity_flag=velocity_flag,
    )
    db.add(r)
    db.flush()
    audit.record(
        db,
        p,
        "refund.requested",
        RES,
        r.id,
        chain=CHAIN,
        reason=reason,
        after={
            "charge_id": t.charge_id,
            "amount_cents": amount_cents,
            "reason_code": reason_code,
            "status": r.status,
            "reserved_before": reserved,
            "approval_why": r.approval_why,
        },
        retention_class="financial",
    )
    if why:
        req = approvals.create_request(
            db,
            p,
            kind="refunds.refund",
            subject_type=RES,
            subject_id=r.id,
            title=f"Refund {amount.format()} on {t.charge_id}",
            reason=reason,
            requirement=approvals.Requirement(
                stages=[approvals.Stage("Finance approver", "refunds.approve")],
                excluded_users=[p.oid],
                note="; ".join(why),
            ),
            chain=CHAIN,
            payload={"amount_cents": amount_cents, "charge_id": t.charge_id},
        )
        r.approval_request_id = req.id
        notify.teams(
            db,
            "refund-approvals",
            "Refund awaiting approval",
            {"Amount": amount.format(), "Charge": t.charge_id, "Requested by": p.name, "Why": "; ".join(why)},
            link=f"/refunds/requests/{r.id}",
        )
    else:
        jobs.enqueue(db, "refunds.execute", {"refund_id": r.id}, dedupe_key=f"refund-exec-{r.id}")
    return r


def on_approved(db: Session, req: ApprovalRequest) -> None:
    r = get_refund(db, system_principal("refunds-approval"), int(req.subject_id), lock=True)
    if r.status != "pending_approval":
        return
    r.status = "approved"
    audit.record(
        db,
        system_principal("refunds-approval"),
        "refund.approved",
        RES,
        r.id,
        chain=CHAIN,
        reason=f"approval request #{req.id} approved",
        before={"status": "pending_approval"},
        after={"status": "approved"},
        retention_class="financial",
    )
    jobs.enqueue(db, "refunds.execute", {"refund_id": r.id}, dedupe_key=f"refund-exec-{r.id}")


def on_rejected(db: Session, req: ApprovalRequest) -> None:
    r = get_refund(db, system_principal("refunds-approval"), int(req.subject_id), lock=True)
    if r.status != "pending_approval":
        return
    r.status = "rejected"  # no longer reserving; the balance is released
    audit.record(
        db,
        system_principal("refunds-approval"),
        "refund.rejected",
        RES,
        r.id,
        chain=CHAIN,
        reason=f"approval request #{req.id} rejected",
        before={"status": "pending_approval"},
        after={"status": "rejected"},
        retention_class="financial",
    )


def _finish(db: Session, r: Refund, status: str, *, processor_ref: str | None = None, why: str) -> None:
    before = {"status": r.status}
    r.status = status
    r.processor_ref = processor_ref or r.processor_ref
    r.executed_at = utcnow()
    audit.record(
        db,
        system_principal("refunds-executor"),
        f"refund.{status}",
        RES,
        r.id,
        chain=CHAIN,
        reason=why,
        before=before,
        after={"status": status, "processor_ref": r.processor_ref, "attempts": r.attempts},
        retention_class="financial",
    )
    notify.teams(
        db,
        "refund-ops",
        f"Refund {status}",
        {"Refund": f"#{r.id}", "Amount": fmt(r.amount_cents, r.currency), "Result": why},
        link=f"/refunds/requests/{r.id}",
    )


def execute(db: Session, payload: dict[str, Any]) -> None:
    sp = system_principal("refunds-executor")
    r = get_refund(db, sp, int(payload["refund_id"]), lock=True)
    if r.status != "approved":
        return  # already executed, failed, or awaiting reconciliation: never send twice
    t = get_txn(db, sp, r.transaction_id)
    r.attempts += 1
    try:
        res = get_processor().refund(t.charge_id, r.amount_cents, r.currency, r.idempotency_key)
    except ProcessorUnknown as e:
        r.status, r.last_error = "unknown", str(e)
        audit.record(
            db,
            system_principal("refunds-executor"),
            "refund.outcome_unknown",
            RES,
            r.id,
            chain=CHAIN,
            reason=f"processor outcome unknown ({e}); reconciling before any retry",
            before={"status": "approved"},
            after={"status": "unknown"},
            retention_class="financial",
        )
        jobs.enqueue(
            db,
            "refunds.reconcile",
            {"refund_id": r.id},
            run_at=utcnow() + timedelta(seconds=30),
            dedupe_key=f"refund-recon-{r.id}",
        )
        return
    except ProcessorRejected as e:
        r.last_error = str(e)
        _finish(db, r, "failed", why=f"processor rejected: {e}")
        return
    _finish(db, r, "succeeded", processor_ref=res["id"], why="processor confirmed")


def reconcile(db: Session, payload: dict[str, Any]) -> None:
    r = get_refund(db, system_principal("refunds-reconciler"), int(payload["refund_id"]), lock=True)
    if r.status != "unknown":
        return
    rec = get_processor().lookup(r.idempotency_key)  # ProcessorUnknown -> job retries with backoff
    if rec is not None:
        _finish(
            db, r, "succeeded", processor_ref=rec["id"], why="reconciled: processor has this idempotency key"
        )
        return
    r.status = "approved"
    audit.record(
        db,
        system_principal("refunds-reconciler"),
        "refund.reconciled_not_found",
        RES,
        r.id,
        chain=CHAIN,
        reason="processor has no refund for this idempotency key; safe to resend with the same key",
        before={"status": "unknown"},
        after={"status": "approved"},
        retention_class="financial",
    )
    jobs.enqueue(db, "refunds.execute", {"refund_id": r.id}, dedupe_key=f"refund-exec-{r.id}")


def reconcile_sweep(db: Session, _: dict[str, Any]) -> None:
    for rid in db.execute(select(Refund.id).where(Refund.status == "unknown")).scalars():
        jobs.enqueue(db, "refunds.reconcile", {"refund_id": rid}, dedupe_key=f"refund-recon-{rid}")


def request_reconcile(db: Session, p: Principal, refund_id: int, reason: str | None) -> Refund:
    reason = require_reason(reason, "a manual reconcile")
    r = get_refund(db, p, refund_id)
    if r.status != "unknown":
        raise Conflict("only refunds with an unknown outcome can be reconciled")
    audit.record(db, p, "refund.reconcile_requested", RES, r.id, chain=CHAIN, reason=reason)
    jobs.enqueue(db, "refunds.reconcile", {"refund_id": r.id}, dedupe_key=f"refund-recon-{r.id}")
    return r


def reveal(db: Session, p: Principal, txn_id: int, field: str, reason: str | None) -> str:
    if not p.has("refunds.pii.reveal"):
        raise Forbidden("missing permission refunds.pii.reveal")
    if field not in PII_FIELDS:
        raise Invalid(f"field must be one of {PII_FIELDS}")
    reason = require_reason(reason, "revealing customer data")
    t = get_txn(db, p, txn_id)
    audit.record(
        db,
        p,
        "refund_transaction.pii_revealed",
        TXN,
        t.id,
        chain=CHAIN,
        reason=reason,
        after={"field": field},
    )
    return str(getattr(t, field))


def stats(db: Session, p: Principal) -> dict[str, Any]:
    q = select(Refund.status, func.count(), func.coalesce(func.sum(Refund.amount_cents), 0)).join(Transaction)
    rows = db.execute(scoped(q, p).group_by(Refund.status)).all()
    return {s: {"count": n, "total_cents": int(c), "total": fmt(int(c))} for s, n, c in rows}
