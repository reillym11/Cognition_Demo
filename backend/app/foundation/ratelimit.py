"""Shared SlowAPI limiter.

Requests are keyed on the client IP, or on the user (`oid`) once the session cookie has been validated against
the DB. Keying on the user rather than the session means opening more sessions does not add budget. Raw cookie
bytes are never used as a key, so rotating a forged cookie cannot mint fresh buckets.

The sign-in routes have their own, looser per-IP tier (`signin_rate_limit`) so an anonymous client cannot use
up a budget that every not-yet-signed-in user behind the same address depends on. That tier keys IPv6 clients on
their /64, since one subscriber usually holds a whole /64 and could otherwise rotate addresses for fresh buckets.
"""

import ipaddress

from fastapi import Depends, Request
from limits import RateLimitItem, parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.foundation.errors import DomainError
from app.foundation.settings import get_settings


def client_key(request: Request) -> str:
    from app.foundation import auth  # auth imports this module for its login routes

    oid = auth.valid_session_oid(request)
    return f"user:{oid}" if oid else f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=client_key, default_limits=[get_settings().rate_limit_default])


def _hit(request: Request, tier: str, limit: RateLimitItem, key: str) -> None:
    endpoint = request.scope.get("endpoint")
    scope = f"{endpoint.__module__}.{endpoint.__qualname__}" if endpoint else "unrouted"
    if not limiter.limiter.hit(limit, tier, scope, key):
        raise DomainError("rate limit exceeded", code="rate_limited", status_code=429)


def _sensitive(request: Request) -> None:
    _hit(request, "sensitive", parse(get_settings().rate_limit_sensitive), client_key(request))


def signin_client_key(request: Request) -> str:
    addr = get_remote_address(request)
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return f"ip:{addr}"
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return f"ip:{ip.ipv4_mapped}"
        return f"ip6:{ipaddress.IPv6Network((ip, 64), strict=False)}"
    return f"ip:{ip}"


def _signin(request: Request) -> None:
    _hit(request, "signin", parse(get_settings().rate_limit_signin), signin_client_key(request))


# Applies settings.rate_limit_sensitive per user (or IP if signed out) per route. Use on reveal and export routes:
#   @router.post("/x/{id}/reveal", dependencies=[sensitive_rate_limit])
sensitive_rate_limit = Depends(_sensitive)
# Applies settings.rate_limit_signin per client IP (IPv6 /64) per route. Only for the public OIDC sign-in routes.
signin_rate_limit = Depends(_signin)
