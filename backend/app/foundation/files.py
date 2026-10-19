"""File intake: size and type checks by magic bytes, active-content rejection, filename sanitisation,
content-addressed storage with SHA-256, integrity check on read, retention metadata, audit."""

import hashlib
import io
import re
from datetime import timedelta
from pathlib import Path

import pikepdf
from sqlalchemy.orm import Session

from app.foundation import audit
from app.foundation.audit import RETENTION_YEARS
from app.foundation.authz import Principal
from app.foundation.db import utcnow
from app.foundation.errors import Invalid, NotFound
from app.foundation.models import StoredFile
from app.foundation.settings import get_settings

MAX_BYTES = 10 * 1024 * 1024
MAGIC = {"application/pdf": b"%PDF-"}
# PDF features that execute or smuggle content; invoices never need them. Matched as decoded names
# (dictionary keys or name values) anywhere in the parsed object graph, never as raw bytes.
ACTIVE_CONTENT = frozenset(
    {
        "/JavaScript",
        "/JS",
        "/Launch",
        "/EmbeddedFile",
        "/EmbeddedFiles",
        "/EF",
        "/OpenAction",
        "/AA",
        "/RichMedia",
        "/RichMediaContent",
        "/XFA",
        "/GoToE",
        "/GoToR",
        "/SubmitForm",
        "/ImportData",
        "/Rendition",
    }
)
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    clean = _NAME_RE.sub("_", base).strip("._")[:100]
    return clean or "upload"


def sniff(content: bytes) -> str:
    for ctype, magic in MAGIC.items():
        if content.startswith(magic):
            return ctype
    raise Invalid("unsupported file type (only PDF is accepted)", code="file_type")


def validate(content: bytes) -> str:
    if not content:
        raise Invalid("empty file", code="file_empty")
    if len(content) > MAX_BYTES:
        raise Invalid(f"file exceeds {MAX_BYTES // (1024 * 1024)} MB", code="file_too_large")
    ctype = sniff(content)
    _reject_active_content(content)
    return ctype


def _active(obj: object, seen: set[tuple[int, int]]) -> bool:
    """Walk direct objects; each indirect object is visited once (the caller iterates the full object table)."""
    if not isinstance(obj, pikepdf.Object):  # numbers, booleans, null come back as Python scalars
        return False
    if obj.is_indirect:
        if obj.objgen in seen:
            return False
        seen.add(obj.objgen)
    if isinstance(obj, pikepdf.Name):
        return str(obj) in ACTIVE_CONTENT
    if isinstance(obj, pikepdf.Stream):
        obj = obj.stream_dict
    if isinstance(obj, pikepdf.Dictionary):
        for key, child in obj.items():
            if str(key) in ACTIVE_CONTENT or _active(child, seen):
                return True
    elif isinstance(obj, pikepdf.Array):
        return any(_active(child, seen) for child in obj)
    return False


def _reject_active_content(content: bytes) -> None:
    rejected = Invalid("PDF contains active or embedded content and was rejected", code="file_active_content")
    try:
        # qpdf decodes #xx name escapes, comments/whitespace and object streams before we inspect names
        with pikepdf.open(io.BytesIO(content)) as pdf:
            # Fail closed on anything a different reader might parse differently: repaired or encrypted files
            if pdf.get_warnings() or pdf.is_encrypted:
                raise Invalid("PDF is damaged or encrypted and was rejected", code="file_malformed")
            seen: set[tuple[int, int]] = set()
            if _active(pdf.trailer, seen) or any(_active(o, seen) for o in pdf.objects):
                raise rejected
            if pdf.get_warnings():
                raise Invalid("PDF is damaged and was rejected", code="file_malformed")
    except Invalid:
        raise
    except Exception as e:  # any parser failure fails closed
        raise Invalid("PDF could not be parsed and was rejected", code="file_malformed") from e


def _path(sha: str) -> Path:
    return Path(get_settings().files_dir) / sha[:2] / sha


def store(
    db: Session, p: Principal, name: str, content: bytes, *, purpose: str, retention_class: str = "financial"
) -> StoredFile:
    ctype = validate(content)
    sha = hashlib.sha256(content).hexdigest()
    path = _path(sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(content)
        tmp.replace(path)
    now = utcnow()
    f = StoredFile(
        sha256=sha,
        size_bytes=len(content),
        content_type=ctype,
        original_name=sanitize_name(name),
        purpose=purpose,
        uploaded_by=p.oid,
        uploaded_at=now,
        retain_until=now + timedelta(days=365 * RETENTION_YEARS.get(retention_class, 3)),
    )
    db.add(f)
    db.flush()
    audit.record(
        db,
        p,
        "file.stored",
        "file",
        f.id,
        chain="files",
        retention_class=retention_class,
        after={"sha256": sha, "size": len(content), "name": f.original_name, "purpose": purpose},
    )
    return f


def read(db: Session, file_id: int) -> tuple[StoredFile, bytes]:
    f = db.get(StoredFile, file_id)
    if f is None:
        raise NotFound("file not found")
    data = _path(f.sha256).read_bytes()
    if hashlib.sha256(data).hexdigest() != f.sha256:
        raise Invalid("stored file failed its integrity check", code="file_integrity")
    return f, data
