# Self-review: startup guard covers the directory API key; region changes end the session

Fixes code scan finding `sfind-97708108b4f7455fb83088546d814184`.

## Files changed
- `backend/app/foundation/settings.py` (protected): `directory_api_key` added to `DEV_ONLY_DEFAULTS`, so a non-dev
  boot with the committed (or an empty) `ITP_DIRECTORY_API_KEY` is refused. String secrets in that list must also be
  at least `MIN_SECRET_LENGTH` (32) chars outside dev.
- `backend/app/foundation/auth.py` (protected): on role revalidation, if the directory's `region` differs from the
  session's, the session is revoked (`directory_region_changed`) instead of re-scoped. The directory can now only
  narrow a live session (roles intersect, disable/region change revoke), never move it into another region.
- `backend/tests/test_settings.py`: per-field case for the directory key, short/empty secret cases, and any `env`
  other than exactly `dev` (`Dev`, `development`, `""`, ...) is checked.
- `backend/app/tools/kyc/tests/test_kyc.py`: `test_directory_region_change_ends_live_session` replaces the old
  re-scope test (region changed to `EU` or cleared → 401 and session revoked).
- `backend/tests/test_foundation.py`: directory-entry edits use `dataclasses.replace` so they keep the region.

## Controls affected
- Directory API credential (roles/region/accountEnabled, mock `/admin/*`): cannot be the public default outside dev.
- Row scope (KYC/refunds `scoped()`): a directory write can no longer grant cross-region access mid-session.

## Tests
- `make test` (full backend suite on Postgres), ruff, ruff format, mypy: pass.
- Removing `directory_api_key` from `DEV_ONLY_DEFAULTS` fails `test_non_dev_refuses_each_dev_default[...DIRECTORY...]`;
  restoring `sess.region = entry.region` fails `test_directory_region_change_ends_live_session`.

## Residual risk
- `ITP_ENV` unset still means `dev`. Unknown values fail closed, but a deploy that omits the variable runs with dev
  defaults. Making it mandatory would need every Make/Procfile/CI entry point to set it.
- After a region-change revoke, re-login takes the region from the IdP token. If the token and directory disagree
  persistently, the user is signed out at each revalidation (fail closed, not a widening).
