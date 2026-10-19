# Self-review: 12 sign-in roles

- `backend/app/tools/refunds/manifest.py`: `Finance.Controller` gains `refunds.approve`. Maker-checker is unchanged:
  the approvals primitive still blocks self-approval and requires a different approver above the threshold.
- `infra/oidc/personas.json`: `finance.approver` becomes a hidden test-only account; `support.contractor` is shown as
  "Outsourced Support (EU)". OIDs, roles and regions unchanged. Login page and dropdown regenerated.
- README role table updated.

`make check` (172 tests) passes.
