# Self-review: AP invoice approval excludes every verifier

Code scan finding `sfind-27c3f848c9a44efdb4818a50b50e7358` (SoD bypass, low).

## Files changed
- `backend/app/tools/ap/models.py`: `Invoice.touched_by` (array of OIDs), like `KycCase.touched_by`.
- `backend/app/tools/ap/service.py`: `verify` appends the verifier to `touched_by`; `requirement_for` excludes
  `uploaded_by`, `verified_by` and everyone in `touched_by`. Before, `verified_by` was overwritten on each verify, so
  an earlier verifier dropped out of `excluded_users` when someone else made a later correction.
- `backend/migrations/versions/0007_ap_touched_by.py` (protected): adds the column, backfills it from `verified_by`.

## Controls affected
- Maker-checker on `ap.invoice` approvals (`foundation.approvals` unchanged; it already rejects excluded users).

## Tests
- `test_every_verifier_is_excluded_from_approving`: a user holding AP.Clerk + AP.Approver verifies one field, a second
  clerk verifies another and submits; the first user is in `excluded_users` and `approvals.decide` raises `Forbidden`.
  It fails on the old code.
- `make check`.

## Residual risk
- Open requests created before this change keep their old `excluded_users` (the requirement is stored at submit
  time). The backfill only recovers the latest verifier for existing invoices; earlier verifiers are in the audit
  log (`ap.invoice.verified`) but not in `touched_by`.
