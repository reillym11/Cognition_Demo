# Self-review: per-user sensitive limit, separate sign-in limit

Fixes code scan findings `sfind-be9092f2ce73481eade4d7c1b4268278` (the sensitive tier was keyed per session, so
one user got a fresh budget for each session they opened) and `sfind-5d25b36434b14f279ad371bcec8d17e2` (the
IP-keyed sensitive tier on public `/api/auth/login` and `/callback` let one anonymous client behind the shared
proxy IP block sign-in for everyone).

## Files changed
- `backend/app/foundation/ratelimit.py`: `client_key` returns `user:<oid>` (taken from the validated session
  row) instead of `session:<id_hash>`, and `ip:<addr>` otherwise. The new `signin_rate_limit` tier is keyed on
  the client IP only and reads `settings.rate_limit_signin`.
- `backend/app/foundation/auth.py` (protected): `valid_session_id` is now `valid_session_oid`. `/login` and
  `/callback` carry `signin_rate_limit` instead of `sensitive_rate_limit`. `/login` deletes the pending
  `OidcLoginState` that the browser's previous binding cookie points to, and redirects with
  `error=signin_busy` once the unexpired states reach `settings.oidc_pending_login_cap`, so it stops creating rows.
- `backend/app/foundation/settings.py`: `rate_limit_signin` (default 120/minute) and `oidc_pending_login_cap`
  (default 5000).
- `web/vite.config.ts`: the proxy sets `xfwd: true`. `Procfile`/`Makefile`: uvicorn runs with `--proxy-headers
  --forwarded-allow-ips 127.0.0.1`. Uvicorn takes the right-most untrusted `X-Forwarded-For` hop, which is the
  one the proxy appended, so the IP key is the real client and a client-supplied XFF value cannot change it.
- `web/src/shell/App.tsx`: adds a message for `signin_busy`.
- `backend/testing.py`: exports `reset_rate_limits`. It was missing from `__all__`, so the autouse reset never
  ran. Per-session keys had hidden this; per-user keys made buckets leak between tests.

## Controls affected
Rate limiting only. Authz, audit, CSRF and the OIDC state/nonce/PKCE/binding checks are unchanged.

## Tests (backend/tests/test_foundation.py)
- `test_rate_limit_key_ignores_forged_session_cookies`: forged cookies map to the IP key, and two separate
  sessions of the same user map to the same `user:<oid>` key.
- `test_sensitive_rate_limit_is_per_user_across_sessions`: once session A uses the budget, session B of the
  same user gets 429 and another user does not. This fails if the key goes back to the session.
- `test_sensitive_routes_carry_sensitive_rate_limit`: reveal and export routes carry the sensitive tier.
  Login and callback carry the sign-in tier and not the sensitive tier.
- `test_signin_limit_is_separate_from_sensitive_and_per_client_ip`: with sensitive set to 1/minute, login still
  works. One IP that runs out of sign-in budget does not block another IP.
- `test_login_caps_pending_states_and_replaces_same_browser_state`: repeated logins from one browser leave a
  single pending state. At the cap, `/login` redirects to `signin_busy` and adds no row.

## Residual risk
- The pending-login cap is global. Enough distinct real IPs, each within its own 120/minute, can still fill
  it. It protects storage; it does not identify clients.
- The count-then-insert is not serialised, so concurrent logins can go slightly over the cap.
- Production ingress isn't defined in this repo. Any real proxy must overwrite or append XFF, and
  `--forwarded-allow-ips` must list only that proxy.
- Limiter storage is still in-memory per process (see the earlier rate-limit self-review). A user's budget is
  per replica until a shared store is used.
