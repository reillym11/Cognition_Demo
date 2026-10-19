# Self-review: rate-limit keying and sensitive-tier limit

Fixes code scan findings `sfind-b1e277a8e2884e26a9a64681ecd015e3` (rate-limit key taken from an unvalidated
session cookie prefix) and `sfind-ab468a474e7c441194a551d498c8ed37` (`rate_limit_sensitive` never applied).

## Files changed
- `backend/app/foundation/ratelimit.py` (new): the shared SlowAPI `limiter`. `client_key` returns
  `session:<id_hash>` only for a live session (it exists, is not revoked, and is within the idle and absolute
  timeouts), and `ip:<addr>` otherwise. `sensitive_rate_limit` is a route dependency that applies
  `settings.rate_limit_sensitive` per client per endpoint and returns 429 `rate_limited`.
- `backend/app/host/main.py`: drops `_key`, which keyed on the first 16 characters of the raw `itp_session`
  cookie, and uses the shared limiter instead.
- `backend/app/foundation/auth.py` (protected): new `valid_session_id(request)`. `/api/auth/login` and
  `/api/auth/callback` now carry `sensitive_rate_limit`.
- Tool routes: every reveal (`kyc`, `refunds`, `complaints`, `ap`) and export (`kyc /export`,
  `refunds /export`, `complaints /register.csv`) carries `sensitive_rate_limit`.
- `backend/testing.py`: an autouse fixture resets limiter storage between tests.

## Controls affected
- Rate limiting only. Authz, audit and masking are unchanged. A forged or expired cookie now falls into the
  client's IP bucket, so rotating cookie values no longer creates new buckets.
- Path-operation `dependencies` run before parameter dependencies, so the sensitive limit is counted before
  authz. Unauthenticated floods of reveal or export routes therefore also hit the limit.

## Tests
- `test_rate_limit_key_ignores_forged_session_cookies`: forged cookies map to the IP key, and a real session
  maps to its id hash.
- `test_sensitive_routes_carry_sensitive_rate_limit`: every reveal, export, `.csv`, login and callback route
  has the dependency.
- `test_sensitive_rate_limit_returns_429`: with the limit set to 2/minute, the third reveal returns 429.

## Residual risk
- `client_key` does one primary-key lookup of `user_sessions` per request. It runs synchronously inside the
  async SlowAPI middleware.
- The IP key uses `request.client.host`. Behind a reverse proxy, every client shares the proxy's IP unless
  uvicorn is run with `--proxy-headers` and trusted forwarded IPs.
- Limiter storage is in memory per process. With several API replicas, each replica keeps its own budget.
  Production would need a shared store such as Redis.
- There is no per-user daily reveal cap and no alert on unusual reveal volume (suggested in the finding).
