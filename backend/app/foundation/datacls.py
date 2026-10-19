"""Data classification registry: one source of truth for masking, log redaction, audit diffs and exports."""

import hashlib
import hmac
import re
from enum import StrEnum
from typing import Any

from app.foundation.settings import get_settings


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"  # e.g. bank details, internal risk scores
    PII = "pii"  # GLBA nonpublic personal information


MASKED_CLASSES = {Classification.PII, Classification.SENSITIVE}


def keyed_hash(value: str) -> str:
    """Deterministic HMAC used for exact-match search and audit fingerprints without storing cleartext."""
    key = get_settings().pii_hash_key.encode()
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()


def mask_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    s = str(value)
    f = field.lower()
    if "ssn" in f or "tax_id" in f:
        return "***-**-" + s[-4:]
    if "email" in f:
        name, _, dom = s.partition("@")
        return (name[:1] + "***@" + dom) if dom else "***"
    if "dob" in f or "birth" in f:
        return "****-**-**"
    if "account" in f or "iban" in f or "routing" in f:
        return "****" + s[-4:]
    if "phone" in f:
        return "***-***-" + s[-4:]
    if "name" in f:
        return " ".join(p[:1] + "***" for p in s.split())
    if "address" in f:
        return "*** (masked)"
    return "***"


def classification_for(resource: str, field: str) -> Classification:
    from app.foundation.registry import get_registry

    return get_registry().classifications.get(resource, {}).get(field, Classification.INTERNAL)


def mask_record(resource: str, record: dict[str, Any]) -> dict[str, Any]:
    """Mask every PII/SENSITIVE field of `resource`. Masked values never leave the server."""
    out = dict(record)
    for k, v in record.items():
        if classification_for(resource, k) in MASKED_CLASSES:
            out[k] = mask_value(k, v)
    return out


def fingerprint_record(resource: str, record: dict[str, Any]) -> dict[str, Any]:
    """For audit diffs: PII/SENSITIVE values become keyed hashes, so changes are provable without storing PII."""
    out: dict[str, Any] = {}
    for k, v in record.items():
        if classification_for(resource, k) in MASKED_CLASSES and v is not None:
            out[k] = {"fp": keyed_hash(str(v))[:16]}
        else:
            out[k] = v
    return out


# Quantifiers are bounded (RFC 5321: local part <= 64, domain <= 255) so each match attempt does
# constant work; unbounded `[\w.+-]+@` is quadratic on long `a.a.a...` runs with no `@`.
_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    (re.compile(r"\b[\w.+-]{1,64}@[\w-]{1,63}\.[\w.-]{1,252}\b"), "[REDACTED-EMAIL]"),
    (re.compile(r"\b\d{9,17}\b"), "[REDACTED-NUMBER]"),
]

REDACT_MAX_CHARS = 32_768
_TRUNCATED = "...[truncated]"


def redact_text(text: str) -> str:
    """Last line of defence for logs: pattern-based redaction of anything PII-shaped.

    Input beyond REDACT_MAX_CHARS is dropped (never emitted unredacted) to bound per-line cost.
    """
    if len(text) > REDACT_MAX_CHARS:
        text = text[:REDACT_MAX_CHARS] + _TRUNCATED
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text
