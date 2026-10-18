---
name: new-internal-tool
description: Build a new internal tool on the shared platform (FastAPI tool package + React page) reusing auth, permissions, audit, approvals, policy, jobs, workflow and file/extraction foundations. Use for any "build a new internal app" request in this repo.
---

# Building a new internal tool

The platform already provides login, permissions, audit, approvals, policy-as-data, jobs, notifications, exports,
a stage engine (`foundation/workflow.py`) and file intake/extraction (`foundation/files.py`, `foundation/extraction.py`).
A new tool is a package under `backend/app/tools/<name>/` plus `web/src/tools/<name>/index.tsx`. It must not add its own
login, role system, audit table or approval logic.

## Steps
1. `make up` then `make new-tool name=<snake_name>` to scaffold the package (manifest, models, routes, service, seed, tests).
2. Declare permissions as `<tool>.<noun>[.<verb>]` and grant them to Entra app roles in `manifest.py`. Every route uses
   `Depends(require("<perm>"))`; startup fails if a route has none.
3. Register sensitive fields under `classifications` so masking, log redaction, audit fingerprints and CSV exports apply.
4. Put every mutation in `service.py`; call `audit.record(...)` in the same transaction, with a reason for anything a
   regulator would ask about. Use `require_reason` for reasons.
5. Use `approvals.create_request` + an `ApprovalKind` hook for any maker-checker step. Exclude everyone who prepared the
   item (`excluded_users`), not just the requester.
6. Put thresholds and limits in `policies` (`PolicyDef`), never in code constants; changing them then needs a second person.
7. Staged processes: define a `WorkflowDef`; tools own persistence. Files: `files.store` + `get_extractor()`.
8. Background work: register `jobs` / `schedules`; jobs act as `system_principal("<job>")`.
9. Money is integer cents + currency. Lock the parent row (`with_for_update`) before checking cumulative limits.
10. `uv run --directory backend alembic revision --autogenerate -m <name> --rev-id <NNNN>`, `make migrate migrate-test`, write a deterministic seed.
11. Build the page with `ui/kit` (DataTable, ApprovalPanel, MaskedField, AuditTimeline, ReasonAction, StageBar).
12. Run `make lint typecheck test openapi` and fix everything; commit to `main` with `[S<n>]` prefix; confirm CI green.

## Tests every tool needs
- Permission denied for a role without the permission (API level).
- Separation of duties: requester/preparer cannot approve; second stage needs a different person.
- Masked fields are masked in API and exports; reveal is permissioned and audited.
- Concurrency for any limit/claim (threads + real Postgres), plus one Hypothesis property test.
- Seed volume and list latency.
