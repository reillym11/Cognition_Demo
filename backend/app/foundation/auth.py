"""OIDC (authorization code + PKCE) backend-for-frontend with server-side sessions.

The browser only ever holds an opaque, HttpOnly session cookie plus a CSRF token cookie. Tokens from the
IdP are validated (signature via JWKS, iss, aud, exp, nonce) and then discarded.
"""

import hashlib
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.foundation import audit
from app.foundation.adapters.directory import get_directory
from app.foundation.authz import Principal, authenticated, public
from app.foundation.db import session_scope
from app.foundation.models import OidcLoginState, UserSession
from app.foundation.registry import get_registry
from app.foundation.settings import get_settings

SESSION_COOKIE = "itp_session"
CSRF_COOKIE = "itp_csrf"
LOGIN_BINDING_COOKIE = "itp_login"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

router = APIRouter(prefix="/api/auth", tags=["auth"])

_oidc_cache: dict[str, Any] = {}


def _oidc_metadata() -> dict[str, Any]:
    if "meta" not in _oidc_cache or time.time() - _oidc_cache["at"] > 300:
        s = get_settings()
        meta = httpx.get(f"{s.oidc_issuer}/.well-known/openid-configuration", timeout=5).json()
        jwks = httpx.get(meta["jwks_uri"], timeout=5).json()
        _oidc_cache.update(meta=meta, jwks=JsonWebKey.import_key_set(jwks), at=time.time())
    return _oidc_cache


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    return value[:300]


def _login_error(code: str) -> RedirectResponse:
    return RedirectResponse(f"{get_settings().public_base_url}/login?error={code}", status_code=303)


@router.get("/login", dependencies=[Depends(public("starts OIDC sign-in"))])
def login(return_to: str | None = None) -> RedirectResponse:
    s = get_settings()
    meta = _oidc_metadata()["meta"]
    state, nonce, verifier, binding = (secrets.token_urlsafe(32) for _ in range(4))
    with session_scope() as db:
        db.execute(
            delete(OidcLoginState).where(
                OidcLoginState.created_at < datetime.now(UTC) - timedelta(minutes=10)
            )
        )
        db.add(
            OidcLoginState(
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                browser_binding=_hash(binding),
                return_to=_safe_return_to(return_to),
            )
        )
    params = {
        "client_id": s.oidc_client_id,
        "response_type": "code",
        "redirect_uri": f"{s.public_base_url}/api/auth/callback",
        "scope": "openid profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": create_s256_code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    resp = RedirectResponse(f"{meta['authorization_endpoint']}?{urlencode(params)}", status_code=303)
    resp.set_cookie(
        LOGIN_BINDING_COOKIE,
        binding,
        httponly=True,
        samesite="lax",
        secure=s.cookie_secure,
        max_age=600,
        path="/api/auth",
    )
    return resp


def roles_from_claims(claims: dict[str, Any]) -> list[str]:
    """Entra app roles first. Groups overage (>200 groups in a JWT) replaces `groups` with `_claim_names`; with no app roles -> deny with a clear error."""
    roles = claims.get("roles")
    if isinstance(roles, list) and roles:
        return sorted(str(r) for r in roles)
    if "groups" in (claims.get("_claim_names") or {}):
        raise PermissionError("groups_overage")
    raise PermissionError("no_roles")


@router.get("/callback", dependencies=[Depends(public("OIDC redirect target"))])
def callback(
    request: Request, code: str | None = None, state: str | None = None, error: str | None = None
) -> Response:
    s = get_settings()
    if error or not code or not state:
        return _login_error("idp_error")
    binding = request.cookies.get(LOGIN_BINDING_COOKIE, "")
    with session_scope() as db:
        st = db.get(OidcLoginState, state)
        if st is None or not secrets.compare_digest(st.browser_binding, _hash(binding)):
            return _login_error("state_mismatch")
        if st.created_at < datetime.now(UTC) - timedelta(minutes=10):
            return _login_error("state_expired")
        db.delete(st)
        nonce, verifier, return_to = st.nonce, st.code_verifier, st.return_to
    cache = _oidc_metadata()
    tok = httpx.post(
        cache["meta"]["token_endpoint"],
        timeout=10,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{s.public_base_url}/api/auth/callback",
            "client_id": s.oidc_client_id,
            "client_secret": s.oidc_client_secret,
            "code_verifier": verifier,
        },
    )
    if tok.status_code != 200 or "id_token" not in tok.json():
        return _login_error("token_exchange_failed")
    try:
        claims = jwt.decode(
            tok.json()["id_token"],
            cache["jwks"],
            claims_options={
                "iss": {"essential": True, "value": s.oidc_issuer},
                "aud": {"essential": True, "value": s.oidc_client_id},
                "nonce": {"essential": True, "value": nonce},
            },
        )
        claims.validate(leeway=30)
    except Exception:
        return _login_error("invalid_token")
    try:
        roles = roles_from_claims(dict(claims))
    except PermissionError as e:
        return _login_error(str(e))
    return _start_session(
        claims["oid"],
        claims.get("preferred_username", claims["oid"]),
        claims.get("name", ""),
        roles,
        claims.get("region"),
        return_to,
    )


def _start_session(
    oid: str, username: str, name: str, roles: list[str], region: str | None, return_to: str
) -> Response:
    s = get_settings()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    with session_scope() as db:
        sess = UserSession(
            id_hash=_hash(token),
            oid=oid,
            username=username,
            name=name,
            roles=roles,
            region=region,
            csrf_token=csrf,
        )
        db.add(sess)
        actor = Principal(
            oid=oid, name=name, username=username, roles=frozenset(roles), permissions=frozenset()
        )
        audit.record(
            db, actor, "auth.login", "session", sess.id_hash[:12], chain="core", after={"roles": roles}
        )
    resp = RedirectResponse(f"{s.public_base_url}{return_to}", status_code=303)
    set_session_cookies(resp, token, csrf)
    resp.delete_cookie(LOGIN_BINDING_COOKIE, path="/api/auth")
    return resp


def set_session_cookies(resp: Response, token: str, csrf: str) -> None:
    s = get_settings()
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure, path="/")
    resp.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="strict", secure=s.cookie_secure, path="/")


def create_session_for_tests(
    oid: str, username: str, name: str, roles: list[str], region: str | None = "US"
) -> tuple[str, str]:
    """Used by tests and the seed CLI only: create a session without the browser OIDC dance."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    with session_scope() as db:
        db.add(
            UserSession(
                id_hash=_hash(token),
                oid=oid,
                username=username,
                name=name,
                roles=roles,
                region=region,
                csrf_token=csrf,
            )
        )
    return token, csrf


def principal_from_request(request: Request) -> Principal:
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    s = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not signed in")
    now = datetime.now(UTC)
    with session_scope() as db:
        sess = db.get(UserSession, _hash(token), with_for_update=False)
        if sess is None or sess.revoked_at is not None:
            raise HTTPException(status_code=401, detail="session ended")
        if now - sess.last_seen_at > timedelta(minutes=s.session_idle_minutes):
            sess.revoked_at, sess.revoked_reason = now, "idle_timeout"
            raise_after = "session expired (idle)"
        elif now - sess.created_at > timedelta(hours=s.session_absolute_hours):
            sess.revoked_at, sess.revoked_reason = now, "absolute_timeout"
            raise_after = "session expired"
        else:
            raise_after = ""
        if not raise_after and now - sess.roles_checked_at > timedelta(seconds=s.roles_revalidate_seconds):
            entry = get_directory().lookup(sess.oid)
            if entry is None or not entry.enabled:
                sess.revoked_at, sess.revoked_reason = now, "directory_disabled"
                raise_after = "account disabled"
            else:
                # The directory can only take roles away; it never adds roles the IdP token did not carry.
                sess.roles = sorted(set(sess.roles) & set(entry.roles))
                sess.region = entry.region
                sess.roles_checked_at = now
        if not raise_after:
            if request.method not in SAFE_METHODS:
                header = request.headers.get("x-csrf-token", "")
                if not header or not secrets.compare_digest(header, sess.csrf_token):
                    raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
            sess.last_seen_at = now
        roles = frozenset(sess.roles)
        p = Principal(
            oid=sess.oid,
            name=sess.name,
            username=sess.username,
            roles=roles,
            permissions=get_registry().permissions_for(roles),
            region=sess.region,
            session_id=sess.id_hash,
        )
    if raise_after:
        raise HTTPException(status_code=401, detail=raise_after)
    request.state.principal = p
    return p


@router.post("/logout")
def logout(request: Request, principal: Principal = Depends(authenticated())) -> Response:
    with session_scope() as db:
        sess = db.get(UserSession, principal.session_id)
        if sess:
            sess.revoked_at, sess.revoked_reason = datetime.now(UTC), "logout"
        audit.record(db, principal, "auth.logout", "session", (principal.session_id or "")[:12], chain="core")
    resp = Response(status_code=204)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    resp.delete_cookie(CSRF_COOKIE, path="/")
    return resp


def revoke_user_sessions(oid: str, reason: str) -> int:
    with session_scope() as db:
        rows = db.execute(
            select(UserSession).where(UserSession.oid == oid, UserSession.revoked_at.is_(None))
        ).scalars()
        n = 0
        for r in rows:
            r.revoked_at, r.revoked_reason = datetime.now(UTC), reason
            n += 1
        return n
