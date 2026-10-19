# Self-review: structural PDF active-content check (code-scan finding sfind-065978af)

**Files (protected):** `backend/app/foundation/files.py`. Also `backend/pyproject.toml`/`uv.lock` (adds `pikepdf`),
`backend/app/tools/ap/tests/test_ap.py`.

## Finding
`files.validate()` searched raw bytes for `/JavaScript`, `/OpenAction`, ... followed by one of `[\s/<(\[]`. Equivalent
encodings bypassed it: name hex escapes (`/J#61vaScript`), NUL/comment/`)` delimiters, and objects inside compressed
`/ObjStm` streams.

## Change
| Control | Where | Test |
|---|---|---|
| PDF parsed with pikepdf (qpdf); names compared after qpdf decodes `#xx` escapes, whitespace/comments and object streams | `files._reject_active_content` | `test_file_validation_rejects_active_content_encodings` (7 encodings), `..._in_object_streams` |
| Every object in the xref table plus the trailer is walked (keys and name values), not just reachable ones | `files._active` | same |
| Fail closed: repaired/damaged, encrypted or unparseable PDFs rejected (`file_malformed`) so a reader that parses differently can't see hidden objects | `files._reject_active_content` | `test_file_validation_fails_closed_on_damaged_or_encrypted_pdf` |
| Denylist extended: `/EmbeddedFiles`, `/EF`, `/RichMediaContent`, `/GoToE`, `/GoToR`, `/SubmitForm`, `/ImportData`, `/Rendition` | `files.ACTIVE_CONTENT` | parametrised test |
| Generated invoices and clean hand-built PDFs still accepted | | `test_file_validation`, all AP ingest tests |

Removing the structural check (reverting to the byte regex) fails the hex-escape, NUL-delimiter and object-stream tests.

## Residual risk
- Still a denylist over the object graph, not content disarm; production should rewrite/flatten (CDR or rasterise) before storage.
- qpdf decodes object streams fully; a highly compressed `/ObjStm` within the 10 MB cap can cost memory/CPU at parse time.
- Strictness may reject legitimately sloppy third-party PDFs (any qpdf repair warning); they surface as `file_malformed` for the clerk to re-request.
- Stored files are still served inline (with `CSP: sandbox`, `nosniff`); unchanged here.
