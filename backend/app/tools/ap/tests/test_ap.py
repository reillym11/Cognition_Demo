import base64

import httpx
import pytest
from sqlalchemy import select

from app.foundation import approvals, audit, files
from app.foundation.db import session_scope
from app.foundation.errors import Conflict, Forbidden, Invalid
from app.foundation.extraction import PdfTextExtractor
from app.foundation.money import parse_cents
from app.foundation.settings import get_settings
from app.tools.ap import pdfgen, service
from app.tools.ap.models import BankChange, Invoice, PurchaseOrder, Vendor
from testing import principal

ACCT, ROUTING = "1234567890", "021000021"


@pytest.fixture
def vendor_po() -> tuple[int, str]:
    with session_scope() as db:
        v = Vendor(
            code="V1",
            name="Acme Supplies",
            phone_on_file="+1-555-0100",
            bank_name="First Synthetic Bank",
            bank_account=ACCT,
            bank_routing=ROUTING,
        )
        db.add(v)
        db.flush()
        db.add(PurchaseOrder(po_number="PO-1", vendor_id=v.id, amount_cents=5_000_000))
        return v.id, "PO-1"


def pdf(
    number: str = "INV-1",
    unit: int = 100_000,
    qty: int = 2,
    po: str | None = "PO-1",
    account: str = ACCT,
    **kw,
) -> bytes:
    return pdfgen.invoice_pdf(
        vendor="Acme Supplies",
        invoice_number=number,
        invoice_date="2026-10-01",
        due_date="2026-10-31",
        po_number=po,
        items=[("Consulting", qty, unit)],
        tax_cents=qty * unit // 10,
        bank_name="First Synthetic Bank",
        account=account,
        routing=ROUTING,
        **kw,
    )


def ingest(content: bytes, who: str = "cleo.clerk") -> int:
    with session_scope() as db:
        return service.ingest(db, principal(who), "invoice.pdf", content).id


def status(iid: int) -> str:
    with session_scope() as db:
        return service.get(db, iid).status


def test_extraction_reads_fields_with_confidence():
    ex = PdfTextExtractor().extract(pdf())
    f = {k: v.value for k, v in ex.fields.items()}
    assert (
        f["invoice_number"] == "INV-1"
        and f["total_cents" if False else "total"] == 220_000
        and f["remit_account"] == ACCT
    )
    assert not ex.warnings and not ex.low_confidence(0.9) and ex.line_items[0]["amount_cents"] == 200_000


def test_garbled_field_needs_verification_then_matches(vendor_po):
    iid = ingest(pdf(garble=["total"]))
    assert status(iid) == "needs_verification"
    with session_scope() as db:
        service.verify(db, principal("cleo.clerk"), iid, {"total_cents": 220_000}, "checked against PDF")
    assert status(iid) == "matched"


def test_duplicates_by_file_and_by_number(vendor_po):
    a = ingest(pdf())
    assert status(ingest(pdf())) == "duplicate"
    b = ingest(pdf(number="inv 0001", unit=100_001))  # normalises to the same number
    assert status(a) == "matched" and status(b) == "duplicate"


def test_po_and_vendor_exceptions(vendor_po):
    assert "po_not_found" in _issues(ingest(pdf(number="X1", po="PO-404")))
    assert "po_amount_exceeded" in _issues(ingest(pdf(number="X2", unit=3_000_000)))


def test_negative_amounts_are_exceptions_and_never_lower_po(vendor_po):
    iid = ingest(pdf(number="CR1", unit=-1_000_000, qty=1))
    assert status(iid) == "exception" and "negative_amount" in _issues(iid)
    with pytest.raises(Conflict), session_scope() as db:
        service.submit(db, principal("cleo.clerk"), iid, "credit note")
    ok = ingest(pdf(number="OK1"))
    with session_scope() as db, pytest.raises(Invalid):
        service.verify(db, principal("cleo.clerk"), iid, {"total_cents": -1}, "typo")
    with session_scope() as db:
        service.submit(db, principal("cleo.clerk"), ok, "ready to pay")
        rid = service.get(db, ok).approval_request_id
    with session_scope() as db:  # amount tampered after submit: approval must not lower invoiced_cents
        service.get(db, ok).total_cents = -1_000_000
    with pytest.raises(Conflict), session_scope() as db:
        approvals.decide(db, principal("abe.approver"), rid, "approve", "matches PO")
    with session_scope() as db:
        assert db.execute(select(PurchaseOrder)).scalar_one().invoiced_cents == 0


def _issues(iid: int) -> list[str]:
    with session_scope() as db:
        return service.get(db, iid).match["issues"]


def test_tiered_sequential_approval_and_separation(vendor_po):
    small = ingest(pdf(number="S1"))
    big = ingest(pdf(number="B1", unit=600_000))  # 1.32M cents incl tax >= 1M tier-2 threshold
    with session_scope() as db:
        service.submit(db, principal("cleo.clerk"), small, "ready to pay")
        service.submit(db, principal("cleo.clerk"), big, "ready to pay")
    with session_scope() as db:
        rid_small, rid_big = (
            service.get(db, small).approval_request_id,
            service.get(db, big).approval_request_id,
        )
    assert rid_small and rid_big
    with session_scope() as db:
        approvals.decide(db, principal("abe.approver"), rid_small, "approve", "matches PO")
    assert status(small) == "approved"
    with session_scope() as db:
        approvals.decide(db, principal("abe.approver"), rid_big, "approve", "matches PO")
    assert status(big) == "pending_approval"
    with session_scope() as db:  # replaying the same decision is idempotent and cannot satisfy stage 2
        approvals.decide(db, principal("abe.approver"), rid_big, "approve", "second time")
    assert status(big) == "pending_approval"
    with session_scope() as db:
        approvals.decide(db, principal("cam.controller"), rid_big, "approve", "controller ok")
    assert status(big) == "approved"
    with session_scope() as db:
        assert db.execute(select(PurchaseOrder)).scalar_one().invoiced_cents == 220_000 + 1_320_000


def test_bank_change_needs_callback_by_other_person_then_third_approver(vendor_po):
    vid, _ = vendor_po
    iid = ingest(pdf(number="BK1", account="9999999999"))
    assert "bank_details_differ" in _issues(iid)
    with session_scope() as db:
        bid = service.request_bank_change(
            db, principal("cleo.clerk"), vid, from_invoice=iid, reason="new details on invoice"
        ).id
    with session_scope() as db, pytest.raises(Forbidden):
        service.record_callback(db, principal("cleo.clerk"), bid, True, "called myself")
    with session_scope() as db:
        service.record_callback(
            db, principal("abe.approver"), bid, True, "Called +1-555-0100 on file; CFO confirmed change"
        )
        rid = db.get(BankChange, bid).approval_request_id
    assert rid
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, principal("abe.approver"), rid, "approve", "I did the call")
    with session_scope() as db:
        approvals.decide(db, principal("cam.controller"), rid, "approve", "verified evidence")
    with session_scope() as db:
        assert db.get(Vendor, vid).bank_account == "9999999999"
    assert status(iid) == "matched"


def test_batch_only_includes_approved_and_is_audited(vendor_po):
    iid = ingest(pdf(number="P1"))
    with session_scope() as db:
        service.submit(db, principal("cleo.clerk"), iid, "ready")
        rid = service.get(db, iid).approval_request_id
    with session_scope() as db:
        approvals.decide(db, principal("abe.approver"), rid, "approve", "ok to pay")
    with session_scope() as db:
        b = service.create_batch(db, principal("cam.controller"), "weekly run")
        assert b.count == 1 and "P1" in b.content and service.get(db, iid).status == "batched"
    with session_scope() as db, pytest.raises(Invalid):
        service.create_batch(db, principal("cam.controller"), "nothing left")


def test_file_validation():
    with pytest.raises(Invalid, match="type"):
        files.validate(b"MZ\x90\x00 not a pdf")
    with pytest.raises(Invalid, match="active"):
        files.validate(b"%PDF-1.4\n1 0 obj << /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>")
    with pytest.raises(Invalid, match="exceeds"):
        files.validate(b"%PDF-" + b"0" * files.MAX_BYTES)
    assert (
        files.sanitize_name("../../etc/passwd") == "passwd"
        and files.sanitize_name("in voice<>.pdf") == "in_voice_.pdf"
    )
    files.validate(pdf())  # our generated PDFs carry no active content


def test_money_parse():
    assert parse_cents("1,234.5") == 123_450 and parse_cents("$7") == 700
    with pytest.raises(ValueError):
        parse_cents("1,2O4.00")


def test_api_masks_bank_details_and_permissions(login, vendor_po):
    c = login("cleo.clerk")
    r = c.post("/api/ap/invoices", files={"file": ("inv.pdf", pdf(number="API1"), "application/pdf")})
    assert r.status_code == 200, r.text
    assert r.json()["remit_account"] != ACCT and r.json()["status"] == "matched"
    assert (
        c.post("/api/ap/invoices", files={"file": ("x.exe", b"MZ\x90", "application/pdf")}).status_code == 422
    )
    assert login("abe.approver").post("/api/ap/batches", json={"reason": "not allowed"}).status_code == 403
    assert login("erin.engineer").get("/api/ap/invoices").status_code == 403
    assert c.get(f"/api/ap/invoices/{r.json()['id']}/file").content.startswith(b"%PDF")


def test_inbox_poll(vendor_po):
    try:
        httpx.post(
            f"{get_settings().mocks_base_url}/ap-inbox/messages",
            json={
                "from": "ap@acme.example.com",
                "filename": "inbox.pdf",
                "content_b64": base64.b64encode(pdf(number="IN1")).decode(),
            },
            timeout=3,
        )
    except httpx.HTTPError:
        pytest.skip("mocks not running")
    with session_scope() as db:
        service.poll_inbox(db, {})
    with session_scope() as db:
        inv = db.execute(select(Invoice).where(Invoice.invoice_number == "IN1")).scalar_one()
        assert inv.source == "inbox" and inv.uploaded_by == "system:ap-inbox"
        assert audit.verify_chain(db, "ap").ok


def test_seed_runs():
    from app.tools.ap import seed

    with session_scope() as db:
        seed.seed(db, 0.2)
    with session_scope() as db:
        st = {s["status"] for s in service.stats(db)["by_status"]}
    assert "matched" in st


def test_resubmit_conflict(vendor_po):
    iid = ingest(pdf(number="R1"))
    with session_scope() as db:
        service.submit(db, principal("cleo.clerk"), iid, "ready")
    with session_scope() as db, pytest.raises(Conflict):
        service.submit(db, principal("cleo.clerk"), iid, "again")
