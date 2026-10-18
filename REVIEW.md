# REVIEW.md — self-review checklist (run before every push; ready for Devin Review if PRs are enabled)

Log findings in `docs/evidence/self-review/<session>.md` as: `severity | file:line | finding | fixed?`.

## Security (block the push)
- [ ] New/changed routes have a permission dependency; permission names exist in a manifest.
- [ ] Row scopes applied on every list/detail query for scoped roles (e.g. contractor region).
- [ ] PII/sensitive fields classified; responses, logs, audit diffs and exports masked.
- [ ] Mutations audited in the same transaction, with reason where it's a decision.
- [ ] Maker-checker via `foundation.approvals`; requester and excluded users can't decide.
- [ ] No raw SQL string interpolation with user input; uploads validated via `foundation.files`.
- [ ] Concurrency: rows that gate money/limits are locked (`with_for_update`) before checks.
- [ ] External calls have timeouts and idempotency keys; unknown outcomes reconciled, not retried blindly.

## Correctness
- [ ] Money is integer cents; currency carried; totals computed in SQL or ints.
- [ ] Thresholds read from policy; tests cover boundary values (=, +1 cent).
- [ ] Tests: unit + integration (real Postgres) + property test for any invariant; e2e for the primary flow.

## Maintainability
- [ ] Reuses the UI kit and foundation helpers; no copy-pasted auth/audit/approval logic.
- [ ] No host edits needed to add a tool. Generated API client updated (`make openapi`).
