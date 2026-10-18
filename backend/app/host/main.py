"""FastAPI host: loads tool manifests, wires middleware, and refuses to start with an unprotected route."""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.foundation import auth
from app.foundation.authz import check_routes
from app.foundation.errors import DomainError
from app.foundation.logging_setup import configure
from app.foundation.registry import get_registry
from app.foundation.request_context import set_request_id
from app.foundation.settings import get_settings

log = logging.getLogger("itp.http")

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self' http://localhost:8081",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        set_request_id(rid[:64])
        start = time.perf_counter()
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        response.headers["X-Request-ID"] = rid[:64]
        principal = getattr(request.state, "principal", None)
        log.info("http.request", extra={
            "method": request.method, "path": request.url.path, "status": response.status_code,
            "ms": round((time.perf_counter() - start) * 1000, 1), "actor": principal.oid if principal else None})
        return response


def _key(request: Request) -> str:
    # Per session when signed in, else per IP.
    return request.cookies.get(auth.SESSION_COOKIE, "")[:16] or get_remote_address(request)


limiter = Limiter(key_func=_key, default_limits=[get_settings().rate_limit_default])


def create_app() -> FastAPI:
    configure()
    reg = get_registry()
    app = FastAPI(title="Internal Tools Platform", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None)
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(RateLimitExceeded)
    def _rate(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse({"detail": "rate limit exceeded", "code": "rate_limited"}, status_code=429)

    @app.exception_handler(DomainError)
    def _domain(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errs = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse({"detail": "validation error", "code": "invalid", "errors": errs}, status_code=422)

    app.include_router(auth.router)
    for m in reg.manifests:
        if m.router is not None:
            app.include_router(m.router)

    problems = check_routes(app, set(reg.permissions))
    if problems:
        raise RuntimeError("refusing to start; deny-by-default violations:\n  " + "\n  ".join(problems))
    return app
