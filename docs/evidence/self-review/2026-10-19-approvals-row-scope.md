# Self-review: approvals respect the subject's row scope (KYC region)

Code scan finding `sfind-057d76598a6c4364ad4866f027cb6244`: a `KYC.Analyst` without `kyc.all_regions` could list,
read and decide `kyc.decision` approval requests for cases outside their region via the core approvals routes.

## Files changed
- `backend/app/foundation/registry.py` (protected-adjacent): `ApprovalKind.can_view(db, req, principal)` optional hook.
- `backend/app/foundation/approvals.py` (protected): `can_decide(db, req, actor)` now also requires
  `can_view_subject()` (the kind's `can_view`; unknown kinds deny, system principals and kinds without a hook pass).
  `decide()` and `to_dict()` use it, so the decide path and the `can_decide` flag both enforce scope.
- `backend/app/foundation/core_manifest.py`: inbox and detail pass `db` to `can_decide`, so out-of-scope requests are
  filtered from `/api/approvals/inbox` and 404 on `/api/approvals/{id}` (requester and `core.audit.read` unchanged).
- `backend/app/tools/kyc/service.py` + `manifest.py`: `can_view_decision` checks the case through `scoped()`.

## Controls affected
- Row scope on approvals (REVIEW.md: "Row scopes applied on every list/detail query for scoped roles").
- Maker-checker invariants unchanged; scope is an extra deny condition.

## Tests
- `test_out_of_region_approver_cannot_see_or_decide`: US analyst doesn't see an EU request in the inbox, gets 404 on
  detail and 403 on decide (API and service); an EU analyst can decide. Fails without the fix (`assert 1 not in {1}`).
- Backend suite: 78 passed, 1 skipped. ruff + mypy clean.

## Residual risk
- Other approval kinds (refunds, AP, flags, policy) have no `can_view`; their subjects aren't region-scoped today. A new
  scoped tool must register `can_view` on its approval kinds.
