# Self-review: file intake + extraction foundation (b20f6e7)

**Files (protected):** `backend/app/foundation/files.py`, `backend/app/foundation/extraction.py`,
`backend/app/foundation/money.py` (`parse_cents`), `backend/migrations/versions/0006_ap.py`.

## Controls
| Control | Where | Test |
|---|---|---|
| PDF-only by magic bytes (not filename/Content-Type) | `files.validate` | `test_file_validation` (MZ header rejected) |
| 10 MB cap; route reads at most `MAX_BYTES + 1` | `files.validate`, `ap/routes.upload` | `test_file_validation` |
| Active content rejected (`/JavaScript`, `/OpenAction`, `/Launch`, `/EmbeddedFile`, ...) | `files.validate` | `test_file_validation` |
| Filename sanitised (no path traversal) | `files.sanitize_name` | `test_file_validation` |
| Content-addressed storage, SHA-256 re-checked on read | `files.store` / `files.read` | via `test_api_masks_bank_details_and_permissions` (file download) |
| PDF served with `Content-Security-Policy: sandbox`, `nosniff`, `no-store`; iframe `sandbox=""` | `ap/routes.invoice_file`, AP UI | manual |
| Money parsed from decimal text, never float | `money.parse_cents` | `test_money_parse` |
| Upload + view are audited in the same transaction | `files.store`, `invoice_file` | `test_inbox_poll` (chain verifies) |

## Residual risk
- Marker scan is a heuristic, not a PDF parser; production should add a CDR/AV step (e.g. sanitise-by-rasterise) before storage.
- Bytes are written to disk before the DB transaction commits; a rollback leaves an orphan content-addressed blob
  (harmless, deduplicated, but needs a sweep job in production).
- Local disk storage only; production needs object storage with retention lock.
- Extraction is a text-layer parser for synthetic PDFs; no accuracy claim against real invoices or AI Builder.
