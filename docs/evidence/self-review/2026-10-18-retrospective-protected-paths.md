# Retrospective self-review: protected-path commits that had no note

The measurement report (`docs/evidence/measurement.md`) found 7 commits that changed protected paths
without a self-review note. This note was written after the fact (2026-10-18), against `REVIEW.md`.
It is retrospective: nobody reviewed these commits before they landed on `main`.

| Commit | Protected files | Controls introduced or changed | Tests that would fail if the control were removed |
|---|---|---|---|
| c6a33ff | `foundation/{auth,authz,audit,approvals,datacls,policy}.py`, migrations `env.py` + `0001`, `infra/oidc/*`, `infra/postgres/init.sql` | OIDC BFF session, deny-by-default route check, hash-chained audit, maker-checker approvals, field classification/masking, policies-as-data, mock Entra personas, DB roles | `test_host_has_no_unprotected_routes`, `test_unprotected_route_is_detected`, `test_csrf_required_on_mutations`, `test_idle_timeout`, `test_role_revocation_takes_effect_mid_session`, `test_groups_overage_is_denied_with_clear_error`, `test_audit_chain_verifies_and_detects_tampering`, `test_audit_chain_concurrent_writers`, `test_policy_change_requires_someone_else`, `test_closed_request_rejects_decisions` |
| 45c9be7 | `.github/workflows/ci.yml`, same foundation files, `0001` | CI gate on push; multi-stage approvals; groups-overage handling; audit triggers blocking UPDATE/DELETE/TRUNCATE; policy value validation | as above, plus `test_policy_value_validation`, `test_audit_diff_keeps_changed_fields_only` |
| 7f0bd7a | migrations `env.py`, `0002_kyc` | append-only `kyc_decisions` trigger; KYC tables | `test_decision_records_are_append_only`, `test_region_row_scope_and_masking` |
| 84da4f5 | `0003_refunds` | refunds tables; cumulative reservation columns | `test_concurrent_requests_never_exceed_captured`, `test_property_reserved_never_exceeds_captured`, `test_over_refund_blocked_including_pending` |
| 47cc7d7 | `0004_flags` | flags + change-history tables | `test_dev_change_applies_and_is_recorded_with_diff`, `test_prod_change_needs_second_person` |
| d09606c | `0005_complaints` | workflow/complaints tables | `test_regulatory_branch_needs_compliance_and_different_person`, `test_compliance_separation_from_investigator` |
| 88ac687 | `.github/ISSUE_TEMPLATE/*` | change-request issue form (Teams fallback). No runtime code. | n/a |

## Checklist (REVIEW.md)
- Deny-by-default and server-side checks: enforced at boot (route check). Weakened by the FastAPI upgrade and re-hardened in 15d0940.
- Reasons on decisions, no self-approval, idempotent decisions: enforced in `approvals.py`, with tests listed above.
- Same-transaction audit: `audit.record` takes the caller's session. No cleartext PII in audit: `fingerprint_record`.
- Append-only: DB triggers on `audit_events` and `kyc_decisions`.

## Gaps the Deep security scan found later (not caught at commit time)
The 19 findings of scan `scan-6b366d0bb0564498b1637cf8d975eaec` include several in these commits: refunds and the approvals inbox had no row scope, session region was never revalidated, JSON policies had no schema, and approvals had no cross-tool scope. They are being fixed in remediation session `fc36370c67584eee827b1c30efcf1b32`. Writing this note after the fact is itself evidence that self-review only at push time missed issues that a review step would likely have caught.
