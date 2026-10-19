# Self-review: ReDoS in log redaction (`datacls.redact_text`)

Fixes code scan finding `sfind-733f184f3e6b4a86bfeea21f40a50fad`.

## Files changed
- `backend/app/foundation/datacls.py` (protected): the email pattern was `\b[\w.+-]+@[\w-]+\.[\w.-]+\b`. On a long `a.a.a...` run with no `@`, each word-boundary start consumed the rest of the run and backtracked, so cost was O(n²): 16 KB took about 0.5 s and 32 KB about 3 s on the event loop. The quantifiers are now bounded to the RFC 5321 limits (`{1,64}@{1,63}\.{1,252}`), so each start position does constant work and the scan is linear. `redact_text` also truncates input to `REDACT_MAX_CHARS` (32 KB) **before** it redacts, so text that is dropped is never emitted unredacted.
- `backend/app/host/main.py`: the `http.request` log keeps only the first 512 characters of the path.
- `backend/tests/test_foundation.py`: tests for redaction output, the adversarial-input time bound, and input truncation.

## Controls affected
- Log, job-error and Teams redaction: the same three PII shapes are still redacted. Email local parts longer than 64 characters (invalid per RFC 5321) are no longer guaranteed to match.
- Availability: one unauthenticated request with a long dotted path can no longer stall the single uvicorn worker.

## Tests
- `test_redact_text_is_linear_on_adversarial_input` takes about 6.5 s with the old pattern and fails its 0.1 s bound. With the new pattern it takes about 25 ms.
- `make check` passes.

## Residual risk
- Log lines longer than 32 KB (for example, long tracebacks) are truncated in the logs.
