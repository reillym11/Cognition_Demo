# Self-review: authenticated directory role revalidation

Code scan finding `sfind-89f0a5f593fd4b5f87e16fe5bb3ce55f`: the role revalidation path trusted an unauthenticated directory
endpoint, and the mock let anyone who could reach :8090 PATCH their own `appRoles`.

## Files changed
- `backend/app/foundation/settings.py`: new `directory_api_key` (`ITP_DIRECTORY_API_KEY`; dev default only).
- `backend/app/foundation/adapters/directory.py`: `HttpDirectory` sends `Authorization: Bearer <key>`.
- `backend/mocks/app.py`: `GET`/`PATCH /directory/users/{oid}` and `POST /admin/*` require the key (constant-time compare), else 401.
- `backend/app/foundation/auth.py` (protected): on revalidation the session's roles become `session roles ∩ directory roles`.
  Session roles start as the validated IdP token's roles and can only shrink, so the directory can revoke but never grant.
- `backend/tests/test_foundation.py`: tests below.

## Controls affected
- Authz: role revalidation can no longer escalate privileges, even if the directory is compromised. Revocation and
  account-disable behaviour are unchanged.
- Mock directory/admin mutations are authenticated.

## Tests
- `test_directory_cannot_add_roles_the_token_did_not_carry`: fails if the intersection is removed.
- `test_mock_directory_and_admin_require_api_key`: no key and wrong key get 401 on all four routes.
- `test_http_directory_sends_api_key`: the adapter authenticates; a wrong key raises.
- Existing `test_role_revocation_takes_effect_mid_session` still passes.
- Backend: ruff, mypy, full pytest on Postgres, OpenAPI drift all pass. Web lint/typecheck not run locally (pnpm missing on VM; no web changes).

## Residual risk
- A role granted in the directory mid-session takes effect only at next login (by design).
- Shared secret, not Graph app credentials over TLS; a real Graph adapter is still needed before production.
