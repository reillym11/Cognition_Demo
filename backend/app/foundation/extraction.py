"""Document field extraction behind an interface. The bundled engine reads the PDF text layer with pdfplumber
and pattern-matches labelled fields; confidence reflects how cleanly each field matched and whether totals
reconcile. It is NOT OCR and makes no accuracy claim for scanned or real-world invoices; an AI extractor
(e.g. Azure Document Intelligence) would implement the same `Extractor` protocol."""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import pdfplumber

from app.foundation.money import parse_cents


@dataclass
class ExtractedField:
    value: Any
    confidence: float


@dataclass
class Extraction:
    engine: str
    fields: dict[str, ExtractedField]
    line_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def low_confidence(self, threshold: float) -> list[str]:
        return [k for k, f in self.fields.items() if f.confidence < threshold]


class Extractor(Protocol):
    name: str

    def extract(self, content: bytes) -> Extraction: ...


LABELS: dict[str, tuple[str, ...]] = {
    "vendor_name": ("Vendor", "From", "Supplier"),
    "invoice_number": ("Invoice Number", "Invoice No", "Invoice #"),
    "invoice_date": ("Invoice Date", "Date"),
    "due_date": ("Due Date", "Payment Due"),
    "po_number": ("PO Number", "Purchase Order", "PO"),
    "currency": ("Currency",),
    "subtotal": ("Subtotal",),
    "tax": ("Tax", "VAT"),
    "total": ("Total Due", "Total", "Amount Due"),
    "remit_bank_name": ("Bank Name", "Bank"),
    "remit_account": ("Account Number", "Account No", "Account"),
    "remit_routing": ("Routing Number", "Routing", "Sort Code"),
}
MONEY = {"subtotal", "tax", "total"}
DATES = {"invoice_date", "due_date"}
LINE_RE = re.compile(r"^(?P<desc>.+?)\s+(?P<qty>\d+)\s+(?P<unit>[\d,]+\.\d{2})\s+(?P<amt>[\d,]+\.\d{2})$")


def _parse(key: str, raw: str) -> Any:
    raw = raw.strip()
    if key in MONEY:
        return parse_cents(raw.replace("$", "").replace(",", ""))
    if key in DATES:
        return date.fromisoformat(raw).isoformat()
    if key == "currency" and not re.fullmatch(r"[A-Z]{3}", raw):
        raise ValueError(raw)
    if key in ("remit_account", "remit_routing"):
        digits = re.sub(r"[\s-]", "", raw)
        if not digits.isdigit():
            raise ValueError(raw)
        return digits
    return raw


class PdfTextExtractor:
    name = "pdf-text-v1"

    def extract(self, content: bytes) -> Extraction:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        out: dict[str, ExtractedField] = {}
        warnings: list[str] = []
        for key, labels in LABELS.items():
            best: ExtractedField | None = None
            for rank, label in enumerate(labels):
                for ln in lines:
                    m = re.match(rf"^{re.escape(label)}\s*[:#]\s*(.+)$", ln, re.IGNORECASE)
                    if not m:
                        continue
                    try:
                        val = _parse(key, m.group(1))
                        conf = 0.97 if rank == 0 else 0.8
                    except ValueError:
                        val, conf = m.group(1).strip(), 0.3
                    if best is None or conf > best.confidence:
                        best = ExtractedField(val, conf)
                    break
            out[key] = best or ExtractedField(None, 0.0)
        items: list[dict[str, Any]] = []
        for ln in lines:
            m = LINE_RE.match(ln)
            if m:
                items.append(
                    {
                        "description": m["desc"],
                        "quantity": int(m["qty"]),
                        "unit_cents": parse_cents(m["unit"].replace(",", "")),
                        "amount_cents": parse_cents(m["amt"].replace(",", "")),
                    }
                )
        sub, tax, tot = (out[k].value for k in ("subtotal", "tax", "total"))
        if items and isinstance(sub, int) and sum(i["amount_cents"] for i in items) != sub:
            warnings.append("line items do not add up to the subtotal")
            out["subtotal"].confidence = min(out["subtotal"].confidence, 0.5)
        if all(isinstance(v, int) for v in (sub, tax, tot)) and sub + tax != tot:
            warnings.append("subtotal + tax does not equal total")
            out["total"].confidence = min(out["total"].confidence, 0.5)
        return Extraction(engine=self.name, fields=out, line_items=items, warnings=warnings)


_extractor: Extractor = PdfTextExtractor()


def get_extractor() -> Extractor:
    return _extractor


def set_extractor(e: Extractor) -> None:
    global _extractor
    _extractor = e
