"""Document field extraction behind an interface. The bundled engine reads the PDF text layer with pdfplumber
and pattern-matches labelled fields; confidence reflects how cleanly each field matched and whether totals
reconcile. It is NOT OCR and makes no accuracy claim for scanned or real-world invoices; an AI extractor
(e.g. Azure Document Intelligence) would implement the same `Extractor` protocol.

Uploads are untrusted, so the PDF parser runs in a separate process with a wall-clock timeout and an address-space
cap, rejects documents over a page limit and stops reading after a character limit."""

import io
import multiprocessing as mp
import re
from dataclasses import dataclass, field
from datetime import date
from multiprocessing.connection import Connection
from multiprocessing.context import ForkServerContext, SpawnContext
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


class ExtractionLimitExceeded(ValueError):
    """The document exceeded a page, time or memory limit and was not extracted."""


MAX_PAGES = 20
MAX_CHARS = 200_000
TIMEOUT_SECONDS = 15.0
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
_LIMIT = "limit"


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


def _limit_memory(max_bytes: int) -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
    except (ImportError, ValueError, OSError):
        pass


def _caused_by_memory(e: BaseException | None) -> bool:
    while e is not None:
        if isinstance(e, MemoryError):
            return True
        e = e.__cause__ or e.__context__
    return False


def _read_text(content: bytes, conn: Connection, max_pages: int, max_chars: int, max_memory: int) -> None:
    """Child-process entry point: sends ("ok", text, truncated), (_LIMIT, message) or ("error", type name)."""
    try:
        _limit_memory(max_memory)
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) > max_pages:
                conn.send((_LIMIT, f"PDF has more than {max_pages} pages"))
                return
            parts: list[str] = []
            size = 0
            for page in pdf.pages:
                t = page.extract_text() or ""
                parts.append(t)
                size += len(t) + 1
                if size > max_chars:
                    break
        text = "\n".join(parts)
        conn.send(("ok", text[:max_chars], len(text) > max_chars))
    except Exception as e:  # malformed PDF internals; only the type crosses the process boundary
        if _caused_by_memory(e):
            conn.send((_LIMIT, "PDF needs too much memory to read"))
        else:
            conn.send(("error", type(e).__name__))
    finally:
        conn.close()


def _mp_context() -> ForkServerContext | SpawnContext:
    if "forkserver" in mp.get_all_start_methods():
        ctx = mp.get_context("forkserver")
        ctx.set_forkserver_preload([__name__])
        return ctx
    return mp.get_context("spawn")


class PdfTextExtractor:
    name = "pdf-text-v1"

    def __init__(
        self,
        *,
        max_pages: int = MAX_PAGES,
        max_chars: int = MAX_CHARS,
        timeout_seconds: float = TIMEOUT_SECONDS,
        max_memory_bytes: int = MAX_MEMORY_BYTES,
    ) -> None:
        self.max_pages = max_pages
        self.max_chars = max_chars
        self.timeout_seconds = timeout_seconds
        self.max_memory_bytes = max_memory_bytes

    def _text(self, content: bytes) -> tuple[str, bool]:
        ctx = _mp_context()
        recv, send = ctx.Pipe(duplex=False)
        proc = ctx.Process(
            target=_read_text,
            args=(content, send, self.max_pages, self.max_chars, self.max_memory_bytes),
            name="pdf-extract",
        )
        proc.start()
        send.close()
        try:
            if not recv.poll(self.timeout_seconds):
                raise ExtractionLimitExceeded(f"PDF took longer than {self.timeout_seconds:g}s to read")
            msg = recv.recv()
        except EOFError:
            raise ExtractionLimitExceeded("PDF reader exceeded its resource limits") from None
        finally:
            if proc.is_alive():
                proc.kill()
            proc.join()
            recv.close()
        if msg[0] == "ok":
            return msg[1], msg[2]
        if msg[0] == _LIMIT:
            raise ExtractionLimitExceeded(msg[1])
        raise ValueError(f"PDF parse failed: {msg[1]}")

    def extract(self, content: bytes) -> Extraction:
        text, truncated = self._text(content)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        out: dict[str, ExtractedField] = {}
        warnings: list[str] = [f"text layer truncated at {self.max_chars} characters"] if truncated else []
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
