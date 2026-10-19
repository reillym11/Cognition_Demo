# Self-review: refuse to boot outside dev with dev-default secrets

Fixes code scan finding sfind-ea36955f2ee84bfa9c8a3f9dce57a45f.

## Files changed
- `backend/app/foundation/settings.py`: a `Settings` model validator rejects `env != "dev"` when `oidc_client_secret`,
  `pii_hash_key` or `cookie_secure` is empty or still has its dev default. The error names the `ITP_*` variables
  to set. Because the check runs in `Settings()`, the API, worker, CLI and migrations all refuse to start.
- `backend/tests/test_settings.py`: tests for dev (allowed), non-dev with every value set (allowed), each dev
  default rejected on its own, all three reported together, and an empty secret rejected.

## Controls affected
- `datacls.keyed_hash` (searchable PII hashes, audit diff fingerprints) can't run outside dev with the public
  repo key. OIDC client auth can't use the committed secret. Session/CSRF cookies are `Secure` outside dev.

## Tests
- `uv run pytest` (full backend suite on Postgres), ruff, mypy: all pass.
- `ITP_ENV=prod python -c "create_app()"` raises a `ValidationError` naming all three variables.

## Residual risk
- `env` is free text. A deployment that leaves `ITP_ENV` unset (or sets it to `dev`) still runs with dev defaults.
  The check stops accidental non-dev boots. It can't stop a misconfigured env label.
- Secret strength (length/entropy) is not checked. Only empty or default values are rejected.
