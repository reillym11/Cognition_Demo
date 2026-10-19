# Self-review: per-requester lock for the refund velocity check

Code scan finding: refund velocity control bypassable via concurrent requests on different charges.

## Files changed
- `backend/app/tools/refunds/service.py`: `request_refund` now takes `lock_requester(db, p.oid)`, a
  `pg_advisory_xact_lock(hashtext('refunds.velocity'), hashtext(oid))`, before the charge row lock and the
  velocity `count()`. The lock is held until commit, so a requester's concurrent requests (on any charges) are
  counted one after another and each sees the others' committed refunds. The two-key form keeps the lock out of
  the single-key space `audit.record` uses. Lock order is now requester, then charge row, then audit chain.
- `backend/app/tools/refunds/tests/test_refunds.py`: `test_concurrent_requests_on_distinct_charges_respect_velocity`
  fires 20 barrier-synchronised requests from one Support.Agent on 20 different charges. It asserts exactly
  `max_requests` (10) are auto-approved and 10 are velocity-flagged.

## Controls affected
- Velocity policy (`refunds.velocity`) for direct-refund roles. Before the fix, the new test saw 20/20 auto-approved
  (3 runs out of 3). After the fix it passes consistently.
- No protected paths touched. No route, permission, audit or masking changes.

## Tests
- `pytest` (backend, real Postgres): all passed. `ruff`, `ruff format --check`, `mypy`: clean.
- Web lint/typecheck not run locally (Node missing from the VM); the web app is unchanged.

## Residual risk
- One requester's refund requests are now processed one at a time. That is acceptable at human request rates.
