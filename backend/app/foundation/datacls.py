"""Data classification registry: one source of truth for masking, log redaction, audit diffs and exports."""

import hashlib
import hmac
import re
from collections.abc import Callable
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


def _mask_all(field: str, value: Any) -> Any:
    """Everything under a classified key is masked, however deeply it is nested (fail closed)."""
    if isinstance(value, dict):
        return {k: _mask_all(field, v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_mask_all(field, v) for v in value]
    return mask_value(field, value)


def _walk(resource: str, value: Any, leaf: Callable[[str, Any], Any]) -> Any:
    if isinstance(value, dict):
        return {
            k: leaf(k, v) if classification_for(resource, k) in MASKED_CLASSES else _walk(resource, v, leaf)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_walk(resource, v, leaf) for v in value]
    return value


def mask_record(resource: str, record: dict[str, Any]) -> dict[str, Any]:
    """Mask every PII/SENSITIVE field of `resource`, at any depth (nested JSON included).
    Masked values never leave the server."""
    out: dict[str, Any] = _walk(resource, record, _mask_all)
    return out


def _fingerprint(field: str, value: Any) -> Any:
    if value is None:
        return None
    return {"fp": keyed_hash(str(value))[:16]}


def fingerprint_record(resource: str, record: dict[str, Any]) -> dict[str, Any]:
    """For audit diffs: PII/SENSITIVE values (at any depth) become keyed hashes, so changes are provable
    without storing PII."""
    out: dict[str, Any] = _walk(resource, record, _fingerprint)
    return out


_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED-SSN]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[REDACTED-EMAIL]"),
    (re.compile(r"\b\d{9,17}\b"), "[REDACTED-NUMBER]"),
]


def redact_text(text: str) -> str:
    """Last line of defence for logs: pattern-based redaction of anything PII-shaped."""
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text
