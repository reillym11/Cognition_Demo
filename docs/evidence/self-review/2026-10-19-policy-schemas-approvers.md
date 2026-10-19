# Self-review: per-policy schemas, per-policy approvers, fail-closed policy reads

Fixes code scan finding sfind-67b2f8452af746a1bb6d2ca0395f73e0: `policy.validate()` accepted any value for
`kind="json"`, and every policy change used the single `core.policy.approve` stage.

## Files changed
- `backend/app/foundation/registry.py`: `PolicyDef` gains `schema` (pydantic model) and `approver` (permission).
  At boot the registry refuses a policy that is not namespaced under its tool, has an unknown kind, has no approver
  declared by its own tool and granted to some role, or is `json` without a schema / with a default that fails it.
- `backend/app/foundation/policy.py` (protected): `validate()` enforces the schema (strict, extra keys forbidden).
  `request_change()` uses the policy's own approver as the stage. `apply_approved()` re-validates the value and
  refuses requests whose stage is not the current approver (covers requests created before this change).
  `get()` validates the stored value; if it's malformed it logs `itp.policy` at error level and returns the vetted default,
  so consumers (`kyc.fastlane_filter`, `sla_due`, `refunds.request_refund`) never index a malformed dict.
- `backend/app/foundation/core_manifest.py`: `core.policy.approve` removed (no longer used); SoD text updated.
- Tool manifests: schemas `FastlaneCriteria` (score 0..35, watch-list hits 0, docs verification required),
  `SlaHours` (1..720h, high <= medium <= low), `Velocity` (window 1 min..7 days, 1..100 requests).
  Approvers: `kyc.policy.approve` → Compliance.Admin; `refunds.policy.approve` and `ap.policy.approve` →
  Finance.Controller.
- `web/src/shell/admin.tsx`: the policy page shows each policy's approver.

## Controls affected
- Maker-checker unchanged (requester excluded, via `foundation.approvals`). Approval is now scoped per domain:
  Platform.Admin can no longer approve any policy; Finance.Controller can't approve KYC criteria.

## Tests
- `tests/test_foundation.py`: wrong-domain approver is Forbidden; weakened/malformed JSON values rejected
  (parametrized); malformed stored value falls back to default; apply re-validates value and approver;
  registry rejects unsafe `PolicyDef`s.
- Backend lint, mypy and pytest pass. Web lint and typecheck pass. No OpenAPI drift.

## Residual risk
- Only Compliance.Admin can approve KYC policies, and only Finance.Controller can approve refunds/AP policies.
  Each demo persona set has one holder, so the requester must be someone else with `core.policy.request`.
- Falling back to the default only logs. There is no Teams alert, because `get()` runs on read paths.
