"""AP invoice intake: file checks -> text-layer extraction with confidence -> human verification when unsure ->
duplicate detection -> vendor + PO two-way match -> amount-tiered sequential approval -> audited payment batch.
Remit-to bank details that differ from the vendor master block payment until a bank change is verified by
call-back (different person) and approved by a controller (third person)."""

import base64
import csv
import hashlib
import io
import re
from datetime import date
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, files, policy
from app.foundation.authz import Principal, system_principal
from app.foundation.datacls import mask_record
from app.foundation.db import utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid, NotFound, require_reason
from app.foundation.extraction import get_extractor
from app.foundation.models import ApprovalRequest
from app.foundation.settings import get_settings
from app.tools.ap.models import BankChange, Invoice, PaymentBatch, PurchaseOrder, Vendor

RES = "ap_invoice"
VENDOR_RES = "ap_vendor"
BANK_RES = "ap_bank_change"
CHAIN = "ap"
TEXT_FIELDS = (
    "vendor_name",
    "invoice_number",
    "po_number",
    "remit_bank_name",
    "remit_account",
    "remit_routing",
)
DATE_FIELDS = ("invoice_date", "due_date")
CENT_FIELDS = {"subtotal": "subtotal_cents", "tax": "tax_cents", "total": "total_cents"}
EDITABLE = (*TEXT_FIELDS, *DATE_FIELDS, *CENT_FIELDS.values())
WORKABLE = ("needs_verification", "exception")


def norm_number(n: str | None) -> str | None:
    """'inv 0001' and 'INV-1' compare equal: drop punctuation/case and leading zeros of digit runs."""
    if not n:
        return None
    s = re.sub(r"[^A-Z0-9]", "", n.upper())
    return re.sub(r"(?<!\d)0+(?=\d)", "", s) or None


def to_dict(i: Invoice) -> dict[str, Any]:
    d = {
        c: getattr(i, c)
        for c in (
            "id",
            "status",
            "source",
            "vendor_id",
            "vendor_name",
            "invoice_number",
            "po_number",
            "currency",
            "subtotal_cents",
            "tax_cents",
            "total_cents",
            "remit_bank_name",
            "remit_account",
            "remit_routing",
            "extraction",
            "line_items",
            "match",
            "duplicate_of",
            "approval_request_id",
            "uploaded_by",
            "verified_by",
            "batch_id",
            "file_id",
            "sha256",
        )
    }
    d["invoice_date"] = i.invoice_date.isoformat() if i.invoice_date else None
    d["due_date"] = i.due_date.isoformat() if i.due_date else None
    d["created_at"] = i.created_at.isoformat()
    return mask_record(RES, d)


def vendor_dict(v: Vendor) -> dict[str, Any]:
    return mask_record(
        VENDOR_RES,
        {
            "id": v.id,
            "code": v.code,
            "name": v.name,
            "phone_on_file": v.phone_on_file,
            "bank_name": v.bank_name,
            "bank_account": v.bank_account,
            "bank_routing": v.bank_routing,
            "bank_verified_at": v.bank_verified_at.isoformat(),
        },
    )


def get(db: Session, iid: int, *, lock: bool = False) -> Invoice:
    q = select(Invoice).where(Invoice.id == iid)
    i = db.execute(q.with_for_update() if lock else q).scalar_one_or_none()
    if i is None:
        raise NotFound("invoice not found")
    return i


def _snapshot(i: Invoice) -> dict[str, Any]:
    return {f: (v.isoformat() if isinstance(v := getattr(i, f), date) else v) for f in EDITABLE}


def ingest(db: Session, p: Principal, name: str, content: bytes, source: str = "upload") -> Invoice:
    f = files.store(db, p, name, content, purpose="ap_invoice")
    prior = (
        db.execute(select(Invoice.id).where(Invoice.sha256 == f.sha256).order_by(Invoice.id))
        .scalars()
        .first()
    )
    try:
        ex = get_extractor().extract(content)
    except Exception as e:  # malformed PDF internals
        raise Invalid("could not read the PDF text layer", code="extract_failed") from e
    vals = {k: fld.value for k, fld in ex.fields.items()}
    inv = Invoice(
        file_id=f.id,
        sha256=f.sha256,
        source=source,
        status="new",
        uploaded_by=p.oid,
        extraction={
            "engine": ex.engine,
            "warnings": ex.warnings,
            "fields": {k: {"value": fld.value, "confidence": fld.confidence} for k, fld in ex.fields.items()},
        },
        line_items=ex.line_items,
        currency=vals.get("currency") if vals.get("currency") == "USD" else "USD",
    )
    for k in TEXT_FIELDS:
        setattr(inv, k, str(vals[k]) if vals.get(k) is not None else None)
    for k in DATE_FIELDS:
        v = vals.get(k)
        setattr(
            inv,
            k,
            date.fromisoformat(v) if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None,
        )
    for k, col in CENT_FIELDS.items():
        setattr(inv, col, vals[k] if isinstance(vals.get(k), int) else None)
    inv.invoice_number_norm = norm_number(inv.invoice_number)
    db.add(inv)
    db.flush()
    low = ex.low_confidence(float(policy.get(db, "ap.confidence_threshold")))
    if prior:
        inv.status, inv.duplicate_of = "duplicate", prior
    elif low or ex.warnings:
        inv.status = "needs_verification"
    else:
        _match(db, inv)
    audit.record(
        db,
        p,
        "ap.invoice.ingested",
        RES,
        inv.id,
        chain=CHAIN,
        retention_class="financial",
        after={
            "status": inv.status,
            "file_sha256": f.sha256,
            "low_confidence": low,
            "warnings": ex.warnings,
            "source": source,
        },
    )
    return inv


def _match(db: Session, inv: Invoice) -> None:
    issues: list[str] = []
    vendor = db.execute(
        select(Vendor).where(func.lower(Vendor.name) == (inv.vendor_name or "").strip().lower())
    ).scalar_one_or_none()
    inv.vendor_id = vendor.id if vendor else None
    if vendor is None:
        issues.append("unknown_vendor")
    elif inv.invoice_number_norm:
        dup = (
            db.execute(
                select(Invoice.id).where(
                    Invoice.vendor_id == vendor.id,
                    Invoice.invoice_number_norm == inv.invoice_number_norm,
                    Invoice.id != inv.id,
                    Invoice.status.notin_(("rejected", "duplicate")),
                )
            )
            .scalars()
            .first()
        )
        if dup:
            inv.status, inv.duplicate_of, inv.match = (
                "duplicate",
                dup,
                {"issues": ["duplicate_invoice_number"]},
            )
            return
    po = (
        db.execute(select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number)).scalar_one_or_none()
        if inv.po_number
        else None
    )
    remaining = None
    if po is None:
        issues.append("po_not_found")
    else:
        remaining = po.amount_cents - po.invoiced_cents
        tol = int(policy.get(db, "ap.po_tolerance_bps"))
        if vendor and po.vendor_id != vendor.id:
            issues.append("po_vendor_mismatch")
        if po.status != "open":
            issues.append("po_closed")
        if inv.total_cents is not None and inv.total_cents * 10_000 > remaining * (10_000 + tol):
            issues.append("po_amount_exceeded")
    if vendor and (inv.remit_account, inv.remit_routing) != (vendor.bank_account, vendor.bank_routing):
        issues.append("bank_details_differ")
    if (
        inv.total_cents is None
        or inv.subtotal_cents is None
        or inv.tax_cents is None
        or inv.subtotal_cents + inv.tax_cents != inv.total_cents
    ):
        issues.append("totals_do_not_reconcile")
    inv.match = {
        "issues": issues,
        "po_remaining_cents": remaining,
        "vendor_code": vendor.code if vendor else None,
    }
    inv.status = "exception" if issues else "matched"


def verify(db: Session, p: Principal, iid: int, fields: dict[str, Any], reason: str | None) -> Invoice:
    reason = require_reason(reason, "verifying invoice fields")
    inv = get(db, iid, lock=True)
    if inv.status not in WORKABLE:
        raise Conflict(f"invoice is {inv.status}; only unverified or exception invoices can be corrected")
    bad = set(fields) - set(EDITABLE)
    if bad:
        raise Invalid(f"not editable: {sorted(bad)}")
    before = _snapshot(inv)
    for k, v in fields.items():
        if k in CENT_FIELDS.values():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise Invalid(f"{k} must be a non-negative integer number of cents")
        elif k in DATE_FIELDS:
            try:
                v = date.fromisoformat(v) if v else None
            except (TypeError, ValueError) as e:
                raise Invalid(f"{k} must be YYYY-MM-DD") from e
        elif k in ("remit_account", "remit_routing"):
            v = re.sub(r"[\s-]", "", str(v or ""))
            if not v.isdigit():
                raise Invalid(f"{k} must be digits")
        else:
            v = str(v).strip() if v is not None else None
        setattr(inv, k, v)
    inv.invoice_number_norm = norm_number(inv.invoice_number)
    inv.verified_by = p.oid
    if p.oid not in (inv.touched_by or []):
        inv.touched_by = [*(inv.touched_by or []), p.oid]
    _match(db, inv)
    audit.record(
        db,
        p,
        "ap.invoice.verified",
        RES,
        inv.id,
        chain=CHAIN,
        reason=reason,
        retention_class="financial",
        before=before,
        after={**_snapshot(inv), "status": inv.status},
    )
    return inv


def reject(db: Session, p: Principal, iid: int, reason: str | None) -> Invoice:
    reason = require_reason(reason, "rejecting an invoice")
    inv = get(db, iid, lock=True)
    if inv.status not in (*WORKABLE, "duplicate", "matched"):
        raise Conflict(f"invoice is {inv.status}")
    before = inv.status
    inv.status = "rejected"
    audit.record(
        db,
        p,
        "ap.invoice.rejected",
        RES,
        inv.id,
        chain=CHAIN,
        reason=reason,
        retention_class="financial",
        before={"status": before},
        after={"status": "rejected"},
    )
    return inv


def requirement_for(db: Session, inv: Invoice) -> approvals.Requirement:
    tier2 = int(policy.get(db, "ap.tier2_threshold_cents"))
    stages = [approvals.Stage("AP approver", "ap.approve")]
    if (inv.total_cents or 0) >= tier2:
        stages.append(approvals.Stage("Financial controller", "ap.approve_tier2"))
    excluded = sorted({x for x in (inv.uploaded_by, inv.verified_by, *(inv.touched_by or [])) if x})
    return approvals.Requirement(
        stages=stages,
        excluded_users=excluded,
        note=f"Invoices of ${tier2 // 100:,} or more need a controller after the AP approver",
    )


def submit(db: Session, p: Principal, iid: int, reason: str | None) -> Invoice:
    reason = require_reason(reason, "submitting for approval")
    inv = get(db, iid, lock=True)
    if inv.status != "matched":
        raise Conflict(f"only matched invoices can be submitted (this one is {inv.status})")
    req = approvals.create_request(
        db,
        p,
        kind="ap.invoice",
        subject_type=RES,
        subject_id=inv.id,
        chain=CHAIN,
        reason=reason,
        title=f"Invoice {inv.invoice_number} · {inv.vendor_name} · ${(inv.total_cents or 0) / 100:,.2f}",
        requirement=requirement_for(db, inv),
        payload={"invoice_id": inv.id, "total_cents": inv.total_cents},
    )
    inv.status, inv.approval_request_id = "pending_approval", req.id
    audit.record(
        db,
        p,
        "ap.invoice.submitted",
        RES,
        inv.id,
        chain=CHAIN,
        reason=reason,
        retention_class="financial",
        after={"status": inv.status, "approval_request_id": req.id},
    )
    return inv


def on_invoice_approved(db: Session, req: ApprovalRequest) -> None:
    inv = get(db, req.payload["invoice_id"], lock=True)
    po = db.execute(
        select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number).with_for_update()
    ).scalar_one()
    tol = int(policy.get(db, "ap.po_tolerance_bps"))
    total = inv.total_cents or 0
    if total * 10_000 > (po.amount_cents - po.invoiced_cents) * (10_000 + tol):
        raise Conflict("PO no longer has enough remaining value for this invoice")
    po.invoiced_cents += total
    inv.status = "approved"
    audit.record(
        db,
        system_principal("ap-approval"),
        "ap.invoice.approved",
        RES,
        inv.id,
        chain=CHAIN,
        retention_class="financial",
        reason=req.request_reason,
        after={"status": "approved", "po_invoiced_cents": po.invoiced_cents},
    )


def on_invoice_rejected(db: Session, req: ApprovalRequest) -> None:
    inv = get(db, req.payload["invoice_id"], lock=True)
    inv.status = "rejected"
    audit.record(
        db,
        system_principal("ap-approval"),
        "ap.invoice.rejected",
        RES,
        inv.id,
        chain=CHAIN,
        retention_class="financial",
        reason="approver rejected",
        after={"status": "rejected"},
    )


# ---------- bank-detail changes ----------


def bank_dict(b: BankChange, vendor: Vendor) -> dict[str, Any]:
    return mask_record(
        BANK_RES,
        {
            "id": b.id,
            "vendor_id": b.vendor_id,
            "vendor_name": vendor.name,
            "phone_on_file": vendor.phone_on_file,
            "status": b.status,
            "new_bank_name": b.new_bank_name,
            "new_account": b.new_account,
            "new_routing": b.new_routing,
            "source_invoice_id": b.source_invoice_id,
            "requested_by": b.requested_by,
            "requested_by_name": b.requested_by_name,
            "request_reason": b.request_reason,
            "callback_by": b.callback_by,
            "callback_notes": b.callback_notes,
            "approval_request_id": b.approval_request_id,
            "created_at": b.created_at.isoformat(),
        },
    )


def request_bank_change(
    db: Session,
    p: Principal,
    vendor_id: int,
    *,
    from_invoice: int | None = None,
    bank_name: str = "",
    account: str = "",
    routing: str = "",
    reason: str | None,
) -> BankChange:
    reason = require_reason(reason, "a bank-detail change")
    v = db.get(Vendor, vendor_id, with_for_update=True)
    if v is None:
        raise NotFound("vendor not found")
    if from_invoice is not None:
        inv = get(db, from_invoice)
        if inv.vendor_id != v.id:
            raise Invalid("invoice belongs to a different vendor")
        bank_name, account, routing = (
            inv.remit_bank_name or "",
            inv.remit_account or "",
            inv.remit_routing or "",
        )
    account, routing = re.sub(r"[\s-]", "", account), re.sub(r"[\s-]", "", routing)
    if (
        not (account.isdigit() and 6 <= len(account) <= 17)
        or not (routing.isdigit() and len(routing) == 9)
        or not bank_name.strip()
    ):
        raise Invalid("need bank name, a 6-17 digit account and a 9-digit routing number")
    if (account, routing) == (v.bank_account, v.bank_routing):
        raise Invalid("these are already the details on file")
    if db.execute(
        select(BankChange.id).where(
            BankChange.vendor_id == v.id, BankChange.status.in_(("pending_callback", "pending_approval"))
        )
    ).first():
        raise Conflict("this vendor already has a bank change in progress")
    b = BankChange(
        vendor_id=v.id,
        new_bank_name=bank_name.strip(),
        new_account=account,
        new_routing=routing,
        source_invoice_id=from_invoice,
        status="pending_callback",
        requested_by=p.oid,
        requested_by_name=p.name,
        request_reason=reason,
    )
    db.add(b)
    db.flush()
    audit.record(
        db,
        p,
        "ap.bank_change.requested",
        BANK_RES,
        b.id,
        chain=CHAIN,
        reason=reason,
        retention_class="financial",
        after={"vendor_id": v.id, "new_account": account, "new_routing": routing},
    )
    return b


def record_callback(db: Session, p: Principal, bid: int, confirmed: bool, notes: str | None) -> BankChange:
    notes = require_reason(notes, "call-back notes")
    b = db.get(BankChange, bid, with_for_update=True)
    if b is None:
        raise NotFound("bank change not found")
    if b.status != "pending_callback":
        raise Conflict(f"bank change is {b.status}")
    if b.requested_by == p.oid:
        raise Forbidden("the requester cannot perform the verification call-back", code="sod_violation")
    b.callback_by, b.callback_notes = p.oid, notes
    if not confirmed:
        b.status = "rejected"
    else:
        req = approvals.create_request(
            db,
            p,
            kind="ap.bank_change",
            subject_type=BANK_RES,
            subject_id=b.id,
            chain=CHAIN,
            reason=notes,
            title=f"Bank change for vendor #{b.vendor_id}",
            requirement=approvals.Requirement(
                stages=[approvals.Stage("Financial controller", "ap.bank.approve")],
                excluded_users=[b.requested_by, p.oid],
                note="Requester, call-back verifier and approver must be three different people",
            ),
            payload={"bank_change_id": b.id},
        )
        b.status, b.approval_request_id = "pending_approval", req.id
    audit.record(
        db,
        p,
        "ap.bank_change.callback",
        BANK_RES,
        b.id,
        chain=CHAIN,
        reason=notes,
        retention_class="financial",
        after={"confirmed": confirmed, "status": b.status},
    )
    return b


def on_bank_approved(db: Session, req: ApprovalRequest) -> None:
    b = db.get(BankChange, req.payload["bank_change_id"], with_for_update=True)
    assert b is not None
    v = db.get(Vendor, b.vendor_id, with_for_update=True)
    assert v is not None
    before = {"bank_name": v.bank_name, "bank_account": v.bank_account, "bank_routing": v.bank_routing}
    v.bank_name, v.bank_account, v.bank_routing, v.bank_verified_at = (
        b.new_bank_name,
        b.new_account,
        b.new_routing,
        utcnow(),
    )
    b.status = "applied"
    actor = system_principal("ap-bank-change")
    audit.record(
        db,
        actor,
        "ap.vendor.bank_updated",
        VENDOR_RES,
        v.id,
        chain=CHAIN,
        retention_class="financial",
        reason=b.request_reason,
        before=before,
        after={"bank_name": v.bank_name, "bank_account": v.bank_account, "bank_routing": v.bank_routing},
    )
    for inv in db.execute(
        select(Invoice).where(Invoice.vendor_id == v.id, Invoice.status == "exception").with_for_update()
    ).scalars():
        _match(db, inv)


def on_bank_rejected(db: Session, req: ApprovalRequest) -> None:
    b = db.get(BankChange, req.payload["bank_change_id"], with_for_update=True)
    assert b is not None
    b.status = "rejected"


def reveal_vendor(db: Session, p: Principal, vendor_id: int, field: str, reason: str | None) -> str:
    reason = require_reason(reason, "revealing bank details")
    if field not in ("bank_account", "bank_routing"):
        raise Invalid("not a revealable field")
    v = db.get(Vendor, vendor_id)
    if v is None:
        raise NotFound("vendor not found")
    audit.record(
        db, p, "ap.vendor.bank_revealed", VENDOR_RES, v.id, chain=CHAIN, reason=reason, after={"field": field}
    )
    return str(getattr(v, field))


# ---------- payment batches ----------


def create_batch(db: Session, p: Principal, reason: str | None) -> PaymentBatch:
    reason = require_reason(reason, "creating a payment batch")
    rows = db.execute(
        select(Invoice, Vendor)
        .join(Vendor, Invoice.vendor_id == Vendor.id)
        .where(Invoice.status == "approved", Invoice.batch_id.is_(None))
        .order_by(Invoice.id)
        .with_for_update(of=Invoice)
    ).all()
    ok = [(i, v) for i, v in rows if (i.remit_account, i.remit_routing) == (v.bank_account, v.bank_routing)]
    if not ok:
        raise Invalid("no approved invoices are ready for payment")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "vendor_code",
            "vendor_name",
            "invoice_number",
            "amount_cents",
            "currency",
            "routing",
            "account",
            "due_date",
        ]
    )
    for i, v in ok:
        w.writerow(
            [
                v.code,
                v.name,
                i.invoice_number,
                i.total_cents,
                i.currency,
                v.bank_routing,
                v.bank_account,
                i.due_date,
            ]
        )
    content = buf.getvalue()
    sha = hashlib.sha256(content.encode()).hexdigest()
    total = sum(i.total_cents or 0 for i, _ in ok)
    batch = PaymentBatch(
        created_by=p.oid,
        created_by_name=p.name,
        count=len(ok),
        total_cents=total,
        sha256=sha,
        content=content,
    )
    db.add(batch)
    db.flush()
    for i, _ in ok:
        i.status, i.batch_id = "batched", batch.id
    audit.record(
        db,
        p,
        "ap.batch.created",
        "ap_batch",
        batch.id,
        chain=CHAIN,
        reason=reason,
        retention_class="financial",
        after={
            "count": len(ok),
            "total_cents": total,
            "sha256": sha,
            "invoice_ids": [i.id for i, _ in ok],
            "skipped_bank_mismatch": [i.id for i, _ in rows if (i, _) not in ok],
        },
    )
    return batch


def batch_file(db: Session, p: Principal, bid: int, reason: str | None) -> PaymentBatch:
    reason = require_reason(reason, "downloading a payment file")
    b = db.get(PaymentBatch, bid)
    if b is None:
        raise NotFound("batch not found")
    if hashlib.sha256(b.content.encode()).hexdigest() != b.sha256:
        raise Invalid("payment file failed its integrity check", code="file_integrity")
    audit.record(
        db,
        p,
        "ap.batch.downloaded",
        "ap_batch",
        b.id,
        chain=CHAIN,
        reason=reason,
        retention_class="financial",
        after={"sha256": b.sha256},
    )
    return b


# ---------- mock inbox ----------


def poll_inbox(db: Session, _: dict[str, Any]) -> None:
    actor = system_principal("ap-inbox")
    r = httpx.post(f"{get_settings().mocks_base_url}/ap-inbox/messages/take", timeout=5)
    r.raise_for_status()
    for m in r.json():
        try:
            with db.begin_nested():
                ingest(db, actor, m.get("filename", "inbox.pdf"), base64.b64decode(m["content_b64"]), "inbox")
        except (Invalid, KeyError, ValueError) as e:
            audit.record(
                db,
                actor,
                "ap.inbox.rejected",
                RES,
                "inbox",
                chain=CHAIN,
                reason=str(e)[:200],
                after={"from": m.get("from"), "filename": files.sanitize_name(str(m.get("filename", "")))},
            )


def stats(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(Invoice.status, func.count(), func.coalesce(func.sum(Invoice.total_cents), 0)).group_by(
            Invoice.status
        )
    ).all()
    return {
        "by_status": [{"status": s, "count": n, "total_cents": int(t or 0)} for s, n, t in rows],
        "bank_changes_open": db.execute(
            select(func.count()).where(BankChange.status.in_(("pending_callback", "pending_approval")))
        ).scalar_one(),
    }
