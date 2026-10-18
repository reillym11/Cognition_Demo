# AGENTS.md — rules for Devin (and humans) working in this repo

Internal tools platform prototype: one FastAPI backend + one React web app. Tools (KYC, refunds, flags,
complaints, AP invoices) are plugins on a shared foundation. **Synthetic data only. No real PII, credentials
or customer systems.**

## Layout
- `backend/app/foundation/` — auth (OIDC BFF), authz, datacls, audit, approvals, policy, jobs, notify, exports,
  money, workflow, files, extraction. **Protected** (see `PROTECTED_PATHS`).
- `backend/app/tools/<key>/` — one package per tool: `manifest.py` (permissions, grants, nav, jobs, policies,
  classifications, approval kinds, seed), `models.py`, `routes.py`, `service.py`, `seed.py`, `tests/`.
- `backend/mocks/` — KYC vendor, payment processor, Teams sink, Entra directory, AP inbox (fault injection).
- `web/src/` — `shell/` (layout, nav, login), `ui/` (shared kit), `tools/<key>/` (pages), `api/` (generated).
- `e2e/` — pytest-playwright suites. `docs/` — evidence, playbook, decisions.

## Commands
`make up` · `make migrate` · `make seed` · `make demo-reset` · `make dev` · `make check` · `make e2e` ·
`make openapi` · `make audit-verify` · `make new-tool name=x`

## Non-negotiable rules
1. Every route declares `Depends(require("<tool>.<perm>"))`, `authenticated()` or `public("why")`. The host
   refuses to boot otherwise. Never check permissions only in the UI.
2. Every mutation and every sensitive read calls `audit.record(...)` **in the same DB session** as the change.
3. Fields holding PII/sensitive data are registered in the tool manifest `classifications`. Never return them
   unmasked except from an audited reveal endpoint.
4. Anything needing a second person goes through `foundation.approvals` (never hand-roll maker-checker).
5. Thresholds/windows/criteria are `PolicyDef`s read via `policy.get()`, never constants.
6. Money is `int` cents + currency. No floats anywhere near money.
7. Every decision requires a reason (`require_reason`).
8. External calls go through an adapter with timeouts; unknown outcomes are modelled explicitly.
9. No secrets in the repo. Local dev values in `settings.py`/compose are marked as such.

## Git (Option B: direct to `main`)
- Small commits prefixed `[S<id>]` (session id) so measurement can attribute them.
- Before every push: `git pull --rebase` then `make check` (the pre-push hook runs it; `make hooks` installs it).
- Tool sessions only touch `backend/app/tools/<key>/`, `web/src/tools/<key>/`, `e2e/test_<key>*.py`, a new
  migration, and docs. Foundation changes are their own commits.
- If `main` is red, fixing it comes first.
- Run the self-review in `REVIEW.md` against your diff and log it in `docs/evidence/self-review/<session>.md`.
