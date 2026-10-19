# Self-review: bounded, streamed audit evidence pack (2026-10-19)

Code scan finding (low, DoS): `GET /api/audit/evidence-pack` accepted any date range, loaded every matching
`AuditEvent` with `.all()`, and built the JSONL and ZIP in memory. A `core.audit.evidence` holder could request
`0001-01-01..9998-12-31` and make the worker hold the whole audit log several times over.

## What changed
| File | Change |
|---|---|
| `backend/app/foundation/core_manifest.py` | Rejects `end < start` (422 `evidence_range_invalid`) and ranges longer than policy `core.evidence_pack_max_days` (default 366, inclusive; 422 `evidence_range_too_long`). Counts events in range before doing any work; refuses above policy `core.evidence_pack_max_events` (default 250 000; 422 `evidence_too_many_events`). Events are read with `yield_per(1000)` and written line by line into a ZIP on a `SpooledTemporaryFile` (spills to disk past 8 MiB), then streamed back in 64 KiB chunks. The audit record is still written in the request transaction before the response. |
| `backend/app/foundation/audit.py` (**protected**) | `verify_chain` reads rows with `yield_per(1000)` instead of buffering the whole chain. Verification logic is unchanged. |
| `backend/tests/test_foundation.py` | Tests: happy path (events present, Content-Length correct, audited with reason); bad ranges (full-calendar range, 367 days, reversed); inclusive 366-day boundary and policy override; event-count cap at `=` and `+1`. |

## REVIEW.md checklist
- Permission dependency unchanged (`core.audit.evidence`); no new routes. OpenAPI unchanged.
- Audit still in the same transaction, with the required reason; `after.events` now comes from the pre-check count.
- Limits are `PolicyDef`s (rule 5), so changing them needs `core.policy.approve` from a second person.
- No PII handling changed: events are serialised with the same `audit.to_dict`.

## Remaining risk
Each pack still verifies every chain end to end (that is what makes the pack evidence). CPU cost grows with the
total log size, the same as `GET /api/audit/verify`, but memory now stays flat. If the log gets large enough for
this to matter, move pack generation to a `foundation.jobs` background job.
