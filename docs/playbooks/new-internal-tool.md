# Playbook: New internal tool on the Cognition_Demo platform (`!new-internal-tool`)

## Overview
Build one new internal tool (e.g. "vendor onboarding", "access review") as a package on the shared platform in
`reillym11/Cognition_Demo`, reusing login, permissions, audit, approvals, policy, jobs, workflow and file/extraction
foundations, and commit it directly to `main` with CI green. The goal is a tool a regulated fintech could put in front of
auditors, not just a UI.

## What's Needed From User
- Tool name and a 3–10 line brief: who uses it, the records it manages, the decisions people make, who must approve what.
- Any thresholds (amounts, SLAs, percentages) and which fields are sensitive (PII, bank details).
- Roles involved (Entra app role names if known; otherwise propose them).

## Procedure
1. Read `AGENTS.md`, `REVIEW.md` and `.agents/skills/new-internal-tool/SKILL.md`; skim one existing tool closest to the brief (`kyc` queues, `refunds` money/limits, `complaints` staged workflow, `ap` documents/approvals).
2. Write a short design note in `docs/tools/<name>.md`: records, states, permissions → roles, approval rules, policies, sensitive fields, jobs, out-of-scope list.
3. Run `make up` and `make new-tool name=<name>`; fill in `models.py`, `manifest.py` (permissions, grants, classifications, policies, approval kinds, jobs, nav, seed).
4. Implement every mutation in `service.py` with same-transaction `audit.record`, reasons via `require_reason`, approvals via `approvals.create_request` + hooks, thresholds via `policy.get`.
5. Add routes with `Depends(require(...))` on every endpoint; mask classified fields in responses and exports; add an audited reveal endpoint if anything is masked.
6. Generate and apply the migration (alembic autogenerate, then `make migrate migrate-test`) and write a deterministic synthetic seed.
7. Write tests: permission denial, separation of duties, masking/reveal audit, concurrency on any limit or claim, one Hypothesis property, seed volume.
8. Build `web/src/tools/<name>/index.tsx` from `ui/kit` components and register its routes; run `make openapi`.
9. Run `make lint typecheck test` and the web `typecheck lint build`; fix all failures.
10. If any file in `PROTECTED_PATHS` changed, follow `.agents/skills/security-review/SKILL.md`.
11. Commit to `main` as `[<tool>] ...`, push, and wait for the CI run on that commit to pass; fix forward if it fails.
12. Append a row to `docs/evidence/sessions.md`: tool, commits, files/lines changed, CI failures before green, time to green, human messages needed.

## Specifications
- No new login, role, audit or approval mechanism; startup route-permission check passes.
- Every decision requiring a reason is audited; `make audit-verify` passes after seeding.
- Preparers can never approve their own work; multi-stage approvals need distinct people.
- Sensitive fields are masked by default in UI, API and CSV exports.
- CI is green on the final commit on `main`.
- Validation: `make check` locally and the GitHub Actions run for the pushed SHA both succeed.

## Advice and Pointers
- Prefer configuration of the existing workflow engine over new state machines; keep the engine small (no parallel stages).
- Money is integer cents; lock the parent row before checking cumulative limits.
- If the brief needs something the foundation lacks, add it to `backend/app/foundation/` with tests in a separate commit first, and note it in the evidence row so per-tool cost isn't inflated.

## Forbidden Actions
- Do not load real customer data or real bank numbers; synthetic only.
- Do not disable CI checks, the pre-push hook's `make check`, or route-permission startup checks to get green.
- Do not hardcode thresholds that a business owner might change.
