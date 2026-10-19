# Self-review: classified fields masked at any depth (AP extraction leak)

Scan finding `sfind-f7f2b8c4c01f48769d39037653d810cf`: `ap.service.to_dict` returned the raw `extraction` JSON, and
`datacls.mask_record` only looked at top-level keys, so `extraction.fields.remit_account.value` /
`remit_routing.value` reached every `ap.read` user unmasked and unaudited (list, detail, verify, submit, reject).

## Files changed
- `backend/app/foundation/datacls.py` (protected): `mask_record` and `fingerprint_record` walk nested dicts/lists.
  A classified key at any depth is masked; if its value is a container, every leaf under it is masked (fail closed).
  Top-level behaviour is unchanged.
- `backend/app/tools/ap/service.py`: `to_dict` no longer serialises raw extraction values. `extraction` is now
  `{engine, warnings, fields: [{field, confidence}]}`; the verified values are the (masked) top-level columns.
- `web/src/tools/ap/index.tsx`: verify form reads confidence from the new list shape.
- `backend/app/tools/ap/tests/test_ap.py`: two tests (below).

## Controls affected
- Masking (rule 3 in AGENTS.md): now covers nested JSON for every tool and for CSV exports (`foundation.exports`).
- Audit diffs: nested classified values are fingerprinted instead of stored in clear.

## Tests (both fail with the fix reverted)
- `test_no_bank_detail_anywhere_in_invoice_json`: neither account nor routing number appears anywhere in the JSON
  of `GET /api/ap/invoices?page_size=200` or the detail endpoint; confidence is still returned.
- `test_mask_record_masks_classified_keys_at_any_depth`: nested dict, list and dict-under-classified-key cases for
  `mask_record` and `fingerprint_record`.

## Residual risk
- Raw extracted values are still stored in `ap_invoice.extraction` (DB); readable only server-side.
- Masking is keyed on field names: a sensitive value stored under an unclassified key is still not masked.
