"""Deny-by-default authorization: every route declares a permission or is explicitly public."""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.routing import APIRoute

log = logging.getLogger("itp.authz")


@dataclass(frozen=True)
class Principal:
    oid: str
    name: str
    username: str
    roles: frozenset[str]
    permissions: frozenset[str]
    region: str | None = None
    session_id: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def has(self, perm: str) -> bool:
        return perm in self.permissions

    @property
    def is_system(self) -> bool:
        return self.oid.startswith("system:")


def system_principal(job: str) -> Principal:
    return Principal(
        oid=f"system:{job}",
        name=f"system:{job}",
        username=f"system:{job}",
        roles=frozenset({"System"}),
        permissions=frozenset(),
    )


def _current_principal(request: Request) -> Principal:
    from app.foundation.auth import principal_from_request

    return principal_from_request(request)


def require(*perms: str) -> Callable[..., Principal]:
    """Route dependency. Use as `principal: Principal = Depends(require("tool.thing.do"))`."""

    def dep(request: Request, principal: Principal = Depends(_current_principal)) -> Principal:
        missing = [p for p in perms if not principal.has(p)]
        if missing:
            log.info(
                "authz.denied", extra={"actor": principal.oid, "missing": missing, "path": request.url.path}
            )
            raise HTTPException(status_code=403, detail=f"missing permission: {', '.join(missing)}")
        return principal

    dep.__itp_permissions__ = perms  # type: ignore[attr-defined]
    return dep


def public(reason: str) -> Callable[[], None]:
    """Mark a route as intentionally unauthenticated (health, OIDC callback)."""

    def dep() -> None:
        return None

    dep.__itp_public__ = reason  # type: ignore[attr-defined]
    return dep


def authenticated() -> Callable[..., Principal]:
    """Any signed-in user (e.g. /me). Still explicit, still checked at startup."""

    def dep(principal: Principal = Depends(_current_principal)) -> Principal:
        return principal

    dep.__itp_permissions__ = ()  # type: ignore[attr-defined]
    return dep


def _declared(dependant: Any) -> tuple[bool, tuple[str, ...]]:
    found = False
    perms: tuple[str, ...] = ()
    stack = [dependant]
    while stack:
        d = stack.pop()
        call = getattr(d, "call", None)
        if call is not None:
            if hasattr(call, "__itp_permissions__"):
                found = True
                perms += call.__itp_permissions__
            if hasattr(call, "__itp_public__"):
                found = True
        stack.extend(d.dependencies)
    return found, perms


def _api_routes(routes: Any) -> Iterator[APIRoute]:
    """Every APIRoute, including those behind FastAPI's lazily-included routers (>=0.13x)."""
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        sub = getattr(r, "original_router", None)
        if sub is not None:
            yield from _api_routes(sub.routes)


def check_routes(app: FastAPI, known_permissions: set[str]) -> list[str]:
    """Return problems: routes with no permission declaration, or referencing unknown permissions."""
    problems = []
    routes = list(_api_routes(app.routes))
    if not routes:
        problems.append("no API routes discovered; route check would pass vacuously")
    for r in routes:
        found, perms = _declared(r.dependant)
        if not found:
            problems.append(f"{sorted(r.methods or ())} {r.path}: no permission dependency (deny-by-default)")
        for p in perms:
            if p not in known_permissions:
                problems.append(f"{sorted(r.methods or ())} {r.path}: unknown permission {p!r}")
    return problems


def route_permissions(app: FastAPI) -> list[dict[str, Any]]:
    out = []
    for r in _api_routes(app.routes):
        found, perms = _declared(r.dependant)
        out.append(
            {
                "methods": sorted(r.methods or ()),
                "path": r.path,
                "permissions": list(perms),
                "declared": found,
            }
        )
    return out
