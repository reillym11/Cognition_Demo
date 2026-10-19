# Self-review: revalidate session region from the directory

Fixes code scan finding `sfind-3e406387b9e74371b2fb0c6bc6c0182a` (stale row-scope region).

## Files changed
- `backend/app/foundation/adapters/directory.py` (protected): `DirectoryEntry` gains `region` (the directory extension attribute used for row scopes); `HttpDirectory` reads it from the directory response.
- `backend/app/foundation/auth.py` (protected): periodic revalidation in `principal_from_request` now sets `sess.region = entry.region` alongside `sess.roles`, so a region change applies within `roles_revalidate_seconds` instead of lasting until the absolute timeout.
- `backend/mocks/app.py`: mock Entra directory returns each persona's `region` and `PATCH /directory/users/{oid}` accepts `region`.
- `backend/testing.py`: `MemoryDirectory` entries carry the persona region.
- `backend/app/tools/kyc/tests/test_kyc.py`: new regression test.

## Controls affected
- Row scope (KYC `service.scoped`): now follows the directory's current region. A missing region in the directory sets the session region to `None`, which `scoped()` maps to `__none__`, so access fails closed.
- Authn/audit/approvals: unchanged.

## Tests
- `test_directory_region_change_rescopes_live_session`: an EU case is hidden from a US analyst; after the directory moves her to EU it becomes visible and the US case is hidden; after the region is cleared both are hidden. Fails without the `auth.py` change.
- Backend lint, format, mypy and the full pytest suite pass locally.

## Residual risk
- Between revalidations (default 60 s) a session still uses the previous region, the same window as role changes.
- A directory that does not expose the region attribute drops region-scoped users to no regional access rather than keeping the login-token claim.
