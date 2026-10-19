# Self-review: browser-facing IdP base for single-origin previews

## Files changed
- `backend/app/foundation/settings.py` (protected): `oidc_browser_issuer` (default empty, so nothing changes locally).
- `backend/app/foundation/auth.py` (protected): when set, only the authorize redirect's issuer prefix is rewritten to
  it. Discovery, JWKS and the token exchange still use `oidc_issuer`, and ID tokens are validated against it.
- `web/vite.config.ts`: `/entra` proxies the local mock Entra ID; `allowedHosts` admits `.devinapps.com` previews.

## REVIEW.md checklist
- No change to state/nonce/PKCE/binding, token validation, roles, routes, audit or row scopes.
- The rewrite is config-only (env), never derived from the request.

## Tests
Sign-in verified end to end through one origin (`ITP_PUBLIC_BASE_URL=http://127.0.0.1:5173`,
`ITP_OIDC_BROWSER_ISSUER=http://127.0.0.1:5173/entra`): every navigation stayed on that origin. `make check` passes.
