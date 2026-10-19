# Self-review: freeze complaint fields once compliance review is reached

Fixes code scan finding sfind-84a0e15b12904b77ac95a748a16f06cd (compliance review separation-of-duties bypass).

## Files changed
- `backend/app/tools/complaints/service.py`: new `editable_fields()` used by `update()`. On a path with
  `compliance_review`, the reviewer can only edit `compliance_notes`, and after review the `respond` stage can only
  edit `response_text` (plus its checklist). Before this, every earlier-stage field (resolution, root cause,
  category, product, summary) stayed editable, so the investigator could swap the resolution after sign-off and
  the reviewer could rewrite the resolution and then approve their own text. Cases without a compliance stage
  behave as before.
- `backend/app/tools/complaints/tests/test_complaints.py`: tests for both directions plus the unreviewed path.

## Controls affected
- Maker-checker on regulatory / unfair-treatment complaints (server-side, in `update()`). No route, authz or
  audit changes. Not a protected path.

## Tests
- `test_compliance_review_freezes_reviewed_fields` fails on the old code and passes with the fix.
- Full backend suite, ruff and mypy pass.

## Residual risk
- There is no reopen flow: a mistake found after review can't be corrected in place. If one is needed it
  should send the case back to `compliance_review` and clear that completer.
