# Self-review: sandboxed PDF structure check and one-at-a-time inbox

Fixes code scan finding `sfind-4f53d64b4b994ee5ac0b91c21f1f525c`. Before this change, `files.validate` ->
`_reject_active_content` opened untrusted PDFs with pikepdf/qpdf in the API or worker process and walked every
object. It had no `RLIMIT_AS` and no timeout, and it ran before the sandboxed extractor. qpdf inflates object and
xref streams, so a small upload could expand to gigabytes. In a probe, a 1.5 GB object stream reached about 2.1 GB
RSS. The inbox job also took the whole queue in one call, so a worker killed by one message lost every later message.

## Files changed
- `backend/app/foundation/sandbox.py` (new): `run(target, *args, timeout_seconds, max_memory_bytes)` runs a
  module-level function in a forkserver child (spawn as fallback) with `RLIMIT_AS` and a wall-clock timeout. The
  child is killed on timeout. `LimitExceeded` covers timeout, memory (`MemoryError` or child death) and
  input-specific limits. `ChildFailed` carries only the exception type name.
- `backend/app/foundation/extraction.py`: `PdfTextExtractor` now uses `sandbox.run`. Its limits, error types and
  messages are unchanged.
- `backend/app/foundation/files.py` (protected): pikepdf parsing now happens only in the sandbox child
  (`_scan_structure`), with a 10 s timeout and a 1 GB address-space cap. The child sets qpdf decode limits of
  64 MB for flate, PNG, TIFF, RunLength and DCT, and caps the object count at `MAX_OBJECTS = 50_000`. Errors map as
  follows:
  - Timeout, memory, object count and qpdf limit errors (nesting, containers) -> `Invalid(code="file_limit")`.
  - Parse failures, repaired files and encrypted files -> `file_malformed` (fails closed, as before).
  - Active content -> `file_active_content` (as before).
- `backend/app/tools/ap/service.py`: `poll_inbox` takes one message per call (`?limit=1`) and processes it in its
  own savepoint. Any exception is audited as `ap.inbox.rejected`, and the loop continues. The audit reason is the
  `Invalid` message or only the exception type name, so no content goes into the log.
- `backend/mocks/app.py`: `/ap-inbox/messages/take` accepts an optional `limit`. Without it, the whole queue is
  returned, as before.

## REVIEW.md checklist
- Routes, permissions, row scopes, classifications and approvals are unchanged.
- Uploads are still validated via `foundation.files`, and validation is now resource-bounded.
- Each inbox rejection is audited in the same session as the savepoint. The audit chain is checked in tests.
- External call: the inbox adapter keeps `timeout=5`. Messages are taken one at a time, so a crash loses at most
  the message in flight.

## Tests (each fails with `files.py`, `service.py` and `mocks/app.py` reverted to `origin/main`)
- `test_file_validation_is_bounded_on_decompression_bombs`: a 200 MB object-stream bomb is rejected. Active
  content hidden behind object-stream padding is still detected.
- `test_file_validation_limits_map_to_file_limit`: object-count, qpdf nesting and timeout breaches all map to
  `file_limit`.
- `test_inbox_poisoned_message_does_not_discard_the_rest`: the queue holds a valid message, a bomb, bad base64, a
  missing field and another valid message. Both valid invoices are ingested, there are 3 rejection audits, the
  chain verifies and the queue ends empty. It runs against the in-process mocks app, so it does not skip in CI.
- `test_inbox_worker_death_leaves_later_messages_queued`: when the worker dies mid-message, the later messages stay
  queued.
- The existing extractor limit tests (pages, time, memory, chars) still pass on the shared sandbox.

## Residual risk
- `RLIMIT_AS` is skipped where `resource` is unavailable (non-POSIX). The timeout still applies.
- Each upload now forks two short-lived children: validate and extract. This is acceptable at prototype volumes.
- The message being processed when the worker is killed is still lost, because the mock inbox has no ack or
  visibility timeout. A real inbox should use peek+ack.
- Limits are constants in `files.py`, which matches the existing `MAX_BYTES` and extractor limits. They are not
  `PolicyDef`s.
