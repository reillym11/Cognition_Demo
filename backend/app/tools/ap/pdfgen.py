"""Synthetic invoice PDFs (ReportLab, text layer). `garble` corrupts named fields to exercise low confidence."""

import io
from collections.abc import Iterable

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def fmt(cents: int) -> str:
    return f"{cents // 100:,}.{cents % 100:02d}"


def invoice_pdf(
    *,
    vendor: str,
    invoice_number: str,
    invoice_date: str,
    due_date: str,
    po_number: str | None,
    items: list[tuple[str, int, int]],
    tax_cents: int,
    bank_name: str,
    account: str,
    routing: str,
    garble: Iterable[str] = (),
) -> bytes:
    g = set(garble)
    subtotal = sum(q * u for _, q, u in items)
    total = subtotal + tax_cents
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1)
    y = 750

    def line(text: str, size: int = 10) -> None:
        nonlocal y
        c.setFont("Helvetica", size)
        c.drawString(72, y, text)
        y -= 16

    line("INVOICE", 16)
    line(f"Vendor: {vendor}")
    line(f"Invoice Number: {invoice_number}")
    line(f"Invoice Date: {'31/31/2026' if 'invoice_date' in g else invoice_date}")
    line(f"Due Date: {due_date}")
    if po_number:
        line(f"PO Number: {po_number}")
    line("Currency: USD")
    y -= 8
    line("Description Qty Unit Amount")
    for desc, q, u in items:
        line(f"{desc} {q} {fmt(u)} {fmt(q * u)}")
    y -= 8
    line(f"Subtotal: {fmt(subtotal)}")
    line(f"Tax: {fmt(tax_cents)}")
    line(f"Total Due: {fmt(total).replace('0', 'O', 1) if 'total' in g else fmt(total)}")
    y -= 8
    line("Remit to")
    line(f"Bank Name: {bank_name}")
    line(f"Account Number: {'12-34X-56' if 'remit_account' in g else account}")
    line(f"Routing Number: {routing}")
    c.showPage()
    c.save()
    return buf.getvalue()
