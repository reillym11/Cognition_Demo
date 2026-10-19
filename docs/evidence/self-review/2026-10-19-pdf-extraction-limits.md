# Self-review: bounded PDF extraction and non-blocking AP upload

Fixes code-scan finding `sfind-7894721d39bd4d4485a0e7a2e7ad86b5` (untrusted PDFs parsed with no page/size/time limit; `async def upload` blocked the event loop).

## Files changed
- `backend/app/foundation/extraction.py`: `PdfTextExtractor` now runs pdfplumber in a child process (forkserver, spawn fallback) and kills it after `TIMEOUT_SECONDS` (15 s). The child sets `RLIMIT_AS` to `MAX_MEMORY_BYTES` (1 GiB), rejects documents with more than `MAX_PAGES` (20) pages before reading any text, and stops at `MAX_CHARS` (200k), adding a "text layer truncated" warning. Breaching a limit raises `ExtractionLimitExceeded` (a `ValueError`). Limits are constructor arguments so tests can tighten them. Not a protected path.
- `backend/app/tools/ap/service.py`: `ingest` maps `ExtractionLimitExceeded` to `Invalid(code="extract_limit")`. The inbox poller already catches `Invalid` and audits `ap.inbox.rejected`, so a poisoned email is rejected once and not retried by the job runner.
- `backend/app/tools/ap/routes.py`: `upload` is a plain `def`, so FastAPI runs it in the threadpool. It reads at most `files.MAX_BYTES + 1` bytes, as before.

## Controls affected
- Authz, audit, masking: unchanged. The upload still requires `ap.upload`, and `files.store` still validates and audits before extraction.

## Tests
- `test_extraction_rejects_too_many_pages`: 21 pages are rejected and 20 are accepted.
- `test_extraction_enforces_timeout_memory_and_char_limits`: covers the timeout, the memory cap and the character cap.
- `test_ingest_rejects_pdf_over_limits`: ingest returns `extract_limit` for both the page-limit and timeout paths.
- Manual check: a 5.8 MB PDF holding a single ~1.5 GB FlateDecode content stream was rejected in about 1 s with "PDF needs too much memory to read".
- ruff, mypy and the backend pytest suite (Postgres) pass. No OpenAPI drift. The web lint and typecheck were not run locally because pnpm is missing on the VM. No web files changed.

## Residual risk
- Each upload starts one extraction process (forked from the forkserver, so it is cheap). Nothing caps how many run at once beyond the threadpool size and `rate_limit_default`.
- `RLIMIT_AS` is best-effort on non-Linux platforms; there the timeout is still enforced.
