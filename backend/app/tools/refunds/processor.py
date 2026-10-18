"""Payment-processor adapter. Timeouts and 5xx are *unknown outcomes*, never assumed failures."""

from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.foundation.settings import get_settings


class ProcessorUnknown(Exception):
    """The refund may or may not have happened; reconcile by idempotency key before retrying."""


class ProcessorRejected(Exception):
    """Definitive refusal; nothing moved."""


class Processor(Protocol):
    def refund(self, charge_id: str, amount_cents: int, currency: str, key: str) -> dict[str, Any]: ...
    def lookup(self, key: str) -> dict[str, Any] | None: ...


class HttpProcessor:
    def __init__(self, client: httpx.Client, timeout: float = 3.0):
        self.client = client
        self.timeout = timeout

    def refund(self, charge_id: str, amount_cents: int, currency: str, key: str) -> dict[str, Any]:
        try:
            r = self.client.post(
                "/processor/v1/refunds",
                json={"charge_id": charge_id, "amount_cents": amount_cents, "currency": currency},
                headers={"Idempotency-Key": key},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise ProcessorUnknown(type(e).__name__) from e
        if r.status_code >= 500:
            raise ProcessorUnknown(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise ProcessorRejected(f"HTTP {r.status_code}: {r.text[:200]}")
        return dict(r.json())

    def lookup(self, key: str) -> dict[str, Any] | None:
        try:
            r = self.client.get(
                "/processor/v1/refunds", params={"idempotency_key": key}, timeout=self.timeout
            )
        except httpx.HTTPError as e:
            raise ProcessorUnknown(type(e).__name__) from e
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise ProcessorUnknown(f"lookup HTTP {r.status_code}")
        return dict(r.json())


_override: Processor | None = None


def set_processor(p: Processor | None) -> None:
    global _override
    _override = p


@lru_cache
def _default() -> HttpProcessor:
    return HttpProcessor(httpx.Client(base_url=get_settings().mocks_base_url))


def get_processor() -> Processor:
    return _override or _default()
