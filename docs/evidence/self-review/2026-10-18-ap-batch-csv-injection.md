# Self-review: AP payment batch CSV formula injection (code scan finding)

## Files changed
- `backend/app/foundation/exports.py`: `_cell` renamed to public `cell` so tools that build their own CSVs reuse the same formula neutralization. Behaviour unchanged.
- `backend/app/tools/ap/service.py`:
  - `create_batch` routes every payment-file cell through `exports.cell`, so a value starting with `= + - @ \t \r` is prefixed with `'`.
  - `invoice_number` must match `[A-Za-z0-9][A-Za-z0-9 ./_-]{0,63}`. An extracted number that fails is treated as low confidence, so the invoice goes to `needs_verification`. `verify` rejects a non-conforming value. `_match` adds an `invalid_invoice_number` issue, so a bad number can't reach `matched`, approval or a batch.
- `backend/app/tools/ap/tests/test_ap.py`: tests that a formula invoice number goes to verification, can't be verified as-is and must be corrected before it matches. A second test forces formula values into the invoice number and vendor name, then checks both are neutralized in the batch file.

## Controls affected
- None of authz, audit, approvals or masking. No route, schema or migration changes.

## Tests
- Backend lint (ruff), mypy, and the full pytest suite on Postgres pass (79 passed, 1 skipped).

## Residual risk
- Batches created before this change store their CSV verbatim (sha256-pinned). Any of them holding a formula cell should be regenerated.
