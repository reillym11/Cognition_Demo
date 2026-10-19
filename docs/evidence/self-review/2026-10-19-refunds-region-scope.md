# Self-review: refunds contractor region row scope

Fixes code scan finding sfind-e1471211b7d6447682d37b1443774fba: the refunds tool had no region on `Transaction` and no
row scope, so `Support.Contractor` (`support.contractor`, region EU, "EU merchants only") could list, open, audit and
request refunds on every merchant's transactions.

## Files changed
- `backend/migrations/versions/0007_refunds_region.py` (protected): adds `refund_transactions.region` (NOT NULL, indexed).
  Existing rows are backfilled from the merchant brand (Contoso/Fabrikam -> EU, else US); no server default is left
  behind, so new rows must set a region explicitly.
- `backend/app/tools/refunds/models.py`, `seed.py`: `Transaction.region`; seed derives it from the merchant
  (`merchant_region`), without consuming the seeded RNG.
- `backend/app/tools/refunds/service.py`: `scoped(q, p)` like KYC: restricts to `p.region` unless the principal holds
  `refunds.all_regions` or is a system principal; a missing region matches nothing. `get_txn` and `get_refund` now take
  the principal and apply the scope (out-of-scope ids -> 404), so `request_refund`, `reveal`, `request_reconcile` and
  every detail route are covered. `stats` is scoped. Jobs/approval hooks pass system principals.
- `backend/app/tools/refunds/routes.py`: `list_transactions`, `_refunds_filtered` (list + export), `stats`,
  `get_refund`, `refund_audit` use the scope.
- `backend/app/tools/refunds/manifest.py`: new `refunds.all_regions`, granted to Support.Agent, Finance.Approver,
  Finance.Controller and Audit.Auditor (their previous effective access). Support.Contractor does not get it.
- `web/src/tools/refunds/index.tsx`: shows the region column/field.

## Controls affected
- Row scope (REVIEW.md "Row scopes applied on every list/detail query for scoped roles"): now enforced server-side on
  every refunds read and mutation path.

## Tests
- `test_contractor_region_row_scope`: casey sees only EU transactions/refunds/stats; US transaction detail, refund
  detail, refund audit and refund creation return 404 and create nothing; Support.Agent still sees all regions.
- `test_missing_region_sees_nothing`: a scoped principal with no region gets 404 on lookup and on refund request.
- Existing refunds tests updated to pass the principal.

## Residual risk
- Region is derived from the merchant brand; a real system would source it from merchant master data.
- `foundation.approvals` inbox/detail is not region-aware. Contractors hold no `refunds.approve`, and every holder of
  it also holds `refunds.all_regions`, so there is no exposure today; a future regional approver role would need it.
