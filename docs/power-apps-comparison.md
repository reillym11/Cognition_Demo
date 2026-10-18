# Power Apps vs Devin-built tools — honest comparison

Scope: the customer's three existing Power Apps tools (~$250K/yr) plus ~10 planned. "Prototype evidence" means
something in this repo demonstrates it; "claim" rows are marked **unverified** until a Microsoft doc is cited.
Pricing/limits are deliberately not restated here from memory — confirm against current Microsoft licensing docs.

| Dimension | Power Apps / Power Platform | Devin-built on this platform | Prototype evidence |
|---|---|---|---|
| Time to a simple form/list app | Very fast for citizen developers | Fast, but needs an engineer-reviewed commit | — (Power Apps better) |
| Non-engineer edits | Visual designer, BPF designer | Issue form → Devin Automation → commit; still code | `.github/ISSUE_TEMPLATE/change-request.yml` |
| Identity | Entra native | Entra via OIDC (mocked here), app roles first | `foundation/auth.py`, `olly.overage` persona |
| Row/field security | Dataverse roles, column security | Code-level scopes + one sensitive-field register | KYC region isolation, masked PII + audited reveal |
| Maker-checker | Approvals connector; separation rules are app logic | Shared primitive: no self-approval, distinct stages, excluded preparers, reasons | `foundation/approvals.py`, tests in every tool |
| Audit | Dataverse auditing (retention configurable) | Hash-chained, same-transaction, changed-fields-only, fingerprinted PII | `make audit-verify`, `make audit-tamper-demo` |
| Money/concurrency correctness | Possible but hard to test in low-code | Integer cents, row locks, property tests | refunds cumulative-reservation tests |
| Testing & change control | Solutions/ALM pipelines; limited unit testing | Full unit/integration/property tests, CI on every push | `.github/workflows/ci.yml` |
| Document AI | AI Builder prebuilt invoice model | Pluggable `Extractor`; prototype parses text-layer PDFs only | `foundation/extraction.py` — accuracy **not evaluated** |
| Hosting/ops/compliance | Microsoft-operated, M365 compliance inherited | Customer must host, back up, monitor, pen-test | README "Honest limits" — Power Apps better |
| Marginal cost of tool N+1 | Per-user/per-app licensing | Engineering + Devin time; shared foundation reused | `docs/evidence/` per-tool commits and diff sizes |

## Recommendation shape
- **Build with Devin** where controls, money movement, complex rules or test coverage matter (KYC, refunds, AP, complaints).
- **Keep Power Apps** for simple departmental forms/lists owned by non-engineers and tightly bound to M365.
- **Complement**: Devin-built services can expose APIs that Power Apps/Automate call, so both coexist on Entra.
