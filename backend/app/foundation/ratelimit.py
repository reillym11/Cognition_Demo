"""Shared SlowAPI limiter.

Requests are keyed on the client IP, or on the session id hash once that session has been validated against
the DB. Raw cookie bytes are never used as a key, so rotating a forged cookie cannot mint fresh buckets.
"""

from fastapi import Depends, Request
from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.foundation.errors import DomainError
from app.foundation.settings import get_settings


def client_key(request: Request) -> str:
    from app.foundation import auth  # auth imports this module for its login routes

    sid = auth.valid_session_id(request)
    return f"session:{sid}" if sid else f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=client_key, default_limits=[get_settings().rate_limit_default])


def _sensitive(request: Request) -> None:
    endpoint = request.scope.get("endpoint")
    scope = f"{endpoint.__module__}.{endpoint.__qualname__}" if endpoint else "unrouted"
    limit = parse(get_settings().rate_limit_sensitive)
    if not limiter.limiter.hit(limit, "sensitive", scope, client_key(request)):
        raise DomainError("rate limit exceeded", code="rate_limited", status_code=429)


# Applies settings.rate_limit_sensitive per client per route. Use on reveal, export and login routes:
#   @router.post("/x/{id}/reveal", dependencies=[sensitive_rate_limit])
sensitive_rate_limit = Depends(_sensitive)
