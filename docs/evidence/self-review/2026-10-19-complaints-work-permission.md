# Self-review: complaints mutation routes require work permission

Code scan finding sfind-5663c21beca2416d865fca92f36948e6 (missing-auth).

## Files changed
- `backend/app/tools/complaints/routes.py`: `PATCH /api/complaints/{cid}` and `POST /api/complaints/{cid}/advance` still declare `require("complaints.read")`, and now also reject callers holding neither `complaints.work` nor `complaints.compliance_review` (403).
- `backend/app/tools/complaints/service.py`: `_require_worker` requires `complaints.work` for non-compliance stages, not just `assigned_to == p.oid`, so a stale assignment no longer grants edit/advance/link. After compliance review the case goes back to the investigator only if the directory still shows them enabled with `complaints.work`. Otherwise (or if the lookup fails) it goes back to the unassigned queue.

## Controls affected
- Authz: the service and the route both check the caller's current permission, not the stored assignment. No foundation or protected paths changed.

## Tests
- `test_stale_assignment_without_work_permission_cannot_progress`: read-only auditor with a stale assignment gets `Forbidden` at the service and 403 from both routes; the case is unchanged.
- `test_hand_back_skips_investigator_who_lost_work_permission`: investigator demoted in the directory, so compliance hand-back leaves the case unassigned.
- Both fail against the previous code.

## Residual risk
- Hand-back adds a directory lookup (3 s timeout) inside the locked transaction. It fails closed (case left unassigned).
