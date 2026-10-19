# Self-review: per-client pending sign-in cap, FIFO eviction instead of signin_busy

Fixes code scan finding `sfind-6050432d50a34e78b6e95ce1d775f22f`. `/api/auth/login` used to count every pending
`OidcLoginState` row in the table and redirect to `signin_busy` once the count reached `oidc_pending_login_cap`
(5000). Anyone could create those rows with a cookie-less `GET`, and each one lived for 10 minutes, so about five
IPs (or a single IPv6 /64) at the 120/minute sign-in limit could block new sign-ins for every user.

## Files changed
- `backend/app/foundation/auth.py` (protected): `/login` no longer refuses. It stores `client_key` (the sha256 of
  `ratelimit.signin_client_key`) on each state and calls `_evict_oldest` twice. The first call deletes this
  client's oldest pending states beyond `oidc_pending_logins_per_client`. The second deletes the oldest states
  overall beyond `oidc_pending_login_cap` (FIFO). The new state is always inserted. The 10-minute TTL becomes the
  `LOGIN_STATE_TTL` constant, which `/login`, the cookie `max_age` and `/callback` all use.
- `backend/app/foundation/ratelimit.py`: `signin_client_key` keys IPv6 clients on their /64, and IPv4-mapped IPv6
  addresses on the IPv4 address. Other IPv4 addresses are keyed as before. The `signin_rate_limit` tier and the
  per-client pending cap both use it.
- `backend/app/foundation/models.py`, `backend/migrations/versions/0009_oidc_login_client_key.py` (protected):
  `oidc_login_states.client_key` (not null; rows that already exist get `''`), with indexes on `client_key` and
  `created_at`.
- `backend/app/foundation/settings.py`: adds `oidc_pending_logins_per_client` (default 10). `oidc_pending_login_cap`
  is now a FIFO storage bound and no longer causes refusals.
- `web/src/shell/App.tsx`: removes the `signin_busy` message, since nothing returns that code any more.

## Controls affected
The pending-login storage bound and the sign-in rate-limit key. State, nonce, PKCE and browser-binding checks in
`/callback` are unchanged. A state can still only be completed by the browser holding its binding cookie, and
only within 10 minutes.

## Tests (backend/tests/test_foundation.py)
- `test_many_clients_at_global_cap_cannot_block_a_fresh_signin`: 8 IPs fill the global cap (set to 5). A new
  client still gets a redirect to the IdP, its state is stored, and the table stays at 5 rows. This fails if
  `/login` goes back to refusing at the cap.
- `test_one_client_flood_only_evicts_its_own_pending_states`: one IP sends 10 cookie-less logins. It keeps only
  `oidc_pending_logins_per_client` rows, and the victim's earlier state survives.
- `test_signin_client_key_groups_ipv6_by_64` and `test_ipv6_prefix_shares_signin_rate_and_pending_budget`:
  addresses in one /64 share the sign-in rate bucket and the pending budget. A different /64 does not.
- `test_login_replaces_same_browser_state`: the same-browser cleanup is unchanged.

## Residual risk
- Once more than `cap / per_client` (500 by default) distinct keys are flooding together, global FIFO eviction
  starts deleting other users' pending states. Those users see `state_mismatch` and have to click sign in again.
  The attacker can shorten other people's sign-in windows, but cannot stop a new sign-in from starting.
- Count, evict and insert are not serialised, so concurrent logins can briefly go over either bound by a few
  rows. The next `/login` trims them.
- The TTL stays at 10 minutes. It was not shortened, to leave time for MFA at the IdP.
- Limiter storage is still in-memory per process, and the IP key still depends on the proxy settings described
  in the earlier sign-in self-review.
