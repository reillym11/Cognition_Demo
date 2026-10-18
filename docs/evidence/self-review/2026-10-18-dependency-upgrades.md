# Self-review: dependency upgrades + route-check hardening (2026-10-18)

Found during the fresh-clone verification (`git clone` → `make setup up demo-reset check`, then `make security`, `make dev`, `make e2e`).

## What changed
| Area | Change | Why |
|---|---|---|
| `backend/pyproject.toml` | FastAPI `<0.120` → `>=0.135` (resolved 0.146, Starlette 0.48 → 1.9) | `pip-audit`: 12 Starlette advisories (PYSEC-2026-161/248/249/1942/2280/2281). |
| `backend/app/foundation/authz.py` (**protected**) | `check_routes`/`route_permissions` walk FastAPI's lazily-included routers; fail closed if zero API routes are discovered | FastAPI ≥0.140 no longer flattens `include_router` routes into `app.routes`. The deny-by-default startup check silently saw **0 routes** and passed. Caught by `test_unprotected_route_is_detected`. |
| `backend/tests/test_foundation.py` | Real app must expose >50 checked routes; empty app must fail the check | Regression tests for the above. |
| `.github/workflows/ci.yml` (**protected**) | `pip-audit --skip-editable` and no longer `continue-on-error` | Previously errored on the local package, so Python deps were never really audited. Now clean, so it gates. |
| `web/package.json` | vite 5 → 6.4, vitest 2 → 4.1, react-router-dom 6 → 7.18, `--passWithNoTests` | `pnpm audit`: 11 advisories. |
| `Makefile`, `Procfile` | `make dev` fixed (Procfile moved to repo root, `uv run --project backend honcho`) | README's `make dev` failed on a fresh clone. |
| `backend/app/host/cli.py` | `audit-tamper-demo` works on any audit row | It required a row with a reason, which a fresh `demo-reset` doesn't produce. |
| `e2e/` | First pytest-playwright suite (10 tests): OIDC login per persona, nav vs server-side 403, PII masking, groups-overage refusal, auditor read-only, logged-out redirect | `make e2e` had collected 0 tests. |

## REVIEW.md checklist
- Deny-by-default still enforced: yes, and now fails closed if discovery breaks again.
- No permission/audit/approval semantics changed: yes. Only discovery of routes changed.
- Regression test added: yes (2 tests).

## Remaining accepted risk
`pnpm audit` still reports 2 advisories in Tailwind 3's build-time dependencies: `braces` (high, ReDoS/stack exhaustion, no patched release) and `postcss-selector-parser` (moderate; the fix needs Tailwind 4). They only run on developer machines and CI during build and are not shipped to the browser. Fixing them means migrating to Tailwind 4.
