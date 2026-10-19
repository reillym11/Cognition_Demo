# Self-review: integrating the 18 scan-fix PRs (#3–#20) into main

Scan: `scan-6b366d0bb0564498b1637cf8d975eaec` (19 findings). Each PR carries its own self-review note in this folder.
This note covers only the integration work done when merging them together.

## Files changed by the integration (beyond the PRs themselves)
- `backend/migrations/versions/0008_refunds_region.py`: #8 and #14 both added revision `0007`; refunds region renumbered to `0008` (revises `0007`) so Alembic has one head.
- `backend/app/foundation/auth.py`: #3 (region from directory) and #11 (directory may only remove roles) edited the same lines; both kept.
- `backend/app/tools/refunds/service.py`: #10 (per-requester velocity lock) and #14 (region-scoped `get_txn`) edited the same line; both kept, lock taken first.
- `backend/app/tools/refunds/manifest.py`: #14 (`refunds.all_regions`) and #20 (`refunds.policy.approve`) grants combined.
- `backend/app/foundation/core_manifest.py`: #16 added core evidence-pack policies; #20 requires every policy to name a namespaced approver and removed `core.policy.approve`. Added `core.policy.approve_core`, granted to Compliance.Admin, as the approver for the two core policies.
- `backend/app/foundation/logging_setup.py`: pikepdf (added by #18) logs an INFO line at import, which landed in `make openapi` stdout and broke the generated JSON; pikepdf logger set to WARNING.
- `web/src/shell/admin.tsx`: #20's approver column re-applied on top of the Fluent UI table.
- Test files: PRs appended tests to the same files; merged by taking every PR's added/changed test functions.

## Controls affected
Separation of duties on policy changes (core policies now need a Compliance.Admin who is not the requester), region row scope
for refunds and KYC approvals, directory revalidation of roles and region, refund velocity serialisation.

## Tests
`make check`: ruff, eslint, mypy, tsc, 153 backend tests, OpenAPI drift: all pass. Registry startup validation fails if
any policy lacks an approver granted to some role (exercised by every test that builds the app).

## Residual risk
- Mocks API key and directory are still local-dev values; production needs Graph with a managed identity.
- PDF parsing still runs pdfplumber/pikepdf on untrusted input, now in a separate process with page, time and memory caps.
