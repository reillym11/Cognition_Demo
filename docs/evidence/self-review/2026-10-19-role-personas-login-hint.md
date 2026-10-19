# Self-review: role-named personas, dropdown sign-in via login_hint

## Files changed
- `backend/app/foundation/auth.py` (protected): `/api/auth/login` accepts an optional `login_hint` and forwards it to
  the IdP authorize URL only when it matches `LOGIN_HINT` (`[A-Za-z0-9._@-]{1,128}`). It is the standard OIDC hint; it
  grants nothing. State, nonce, PKCE, browser binding, token validation and role mapping are unchanged, and the
  identity still comes only from the signed ID token.
- `infra/oidc/personas.json`: 13 role-named personas offered at sign-in; 4 test-only personas marked `hidden`.
  OIDs, roles and regions unchanged.
- `scripts/gen_login_page.py`: the mock IdP page submits the persona named by `login_hint`; it also generates
  `web/src/shell/personas.gen.ts` (offered personas only) for the sign-in dropdown.
- `web/src/shell/App.tsx`: sign-in dropdown grouped by app. Display only; access is enforced server-side.
- Tests/e2e/README: persona usernames renamed; e2e signs in through the dropdown.
- UI text: em dashes removed (`---` for empty values, `:` as separator); `make dash-check` added to `make check`.

## REVIEW.md checklist
- No route, permission, row scope, classification, audit or approval change.
- `login_hint` is validated before use and never reflected into HTML by the API.
- Mock IdP only: a real Entra tenant would show its own account picker and ignore unknown hints.

## Tests
`make check` (168 backend tests) and `make e2e` (10, including the hidden groups-overage persona) pass.
