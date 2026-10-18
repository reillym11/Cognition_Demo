# Power Apps vs Devin-built tools — honest comparison

Scope: the customer's three existing Power Apps tools (~$250K/yr) plus ~10 planned. "Prototype evidence" means
something in this repo demonstrates it. Every Power Apps / Power Platform statement below links to the official
Microsoft page it was checked against (all links checked 2026-10; full list under [Sources](#sources)). Statements
with no official source are marked **(unverified)**. Microsoft prices are USD list prices, change often, and should be
re-checked before any customer conversation.

| Dimension | Power Apps / Power Platform | Devin-built on this platform | Prototype evidence |
|---|---|---|---|
| Time to a simple form/list app | Very fast for citizen developers — Microsoft describes Power Apps as "a rapid development environment to build custom apps" [[1]](https://learn.microsoft.com/en-us/power-apps/powerapps-overview) | Fast, but needs an engineer-reviewed commit | — (Power Apps better) |
| Non-engineer edits | Visual designer, BPF (business process flow) designer [[2]](https://learn.microsoft.com/en-us/power-automate/create-business-process-flow). BPF limits: 10 active BPFs per table, 30 stages per process, 30 steps per stage, 5 tables per multi-table process [[2]](https://learn.microsoft.com/en-us/power-automate/create-business-process-flow) [[3]](https://learn.microsoft.com/en-us/power-automate/business-process-flows-overview) | Issue form → Devin Automation → commit; still code | `.github/ISSUE_TEMPLATE/change-request.yml` |
| Identity | Entra native: Power Platform sign-in uses the Microsoft Entra auth code flow [[4]](https://learn.microsoft.com/en-us/power-platform/admin/security/authenticate-services) | Entra via OIDC (mocked here), app roles first. Entra omits the `groups` claim above 200 groups (JWT; 150 for SAML) and emits a `_claim_names`/`_claim_sources` overage claim instead [[5]](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference) | `foundation/auth.py`, `olly.overage` persona |
| Row/field security | Dataverse security roles [[6]](https://learn.microsoft.com/en-us/power-platform/admin/security-roles-privileges) and column-level security (optional masking); column security doesn't apply to system administrators [[7]](https://learn.microsoft.com/en-us/power-platform/admin/field-level-security) | Code-level scopes + one sensitive-field register | KYC region isolation, masked PII + audited reveal |
| Maker-checker | Approvals connector (four approval types, incl. everyone-must-approve, first-to-respond and sequential) [[8]](https://learn.microsoft.com/en-us/power-automate/get-started-approvals); separation rules (e.g. no self-approval) are app logic — no built-in rule is documented on that page **(unverified)** | Shared primitive: no self-approval, distinct stages, excluded preparers, reasons | `foundation/approvals.py`, tests in every tool |
| Audit | Dataverse auditing; retention configurable (default Forever, custom up to 24,855 days); logs use Dataverse log capacity; retrieve/export operations aren't covered by auditing (separate activity logging to Purview) [[9]](https://learn.microsoft.com/en-us/power-platform/admin/manage-dataverse-auditing) | Hash-chained, same-transaction, changed-fields-only, fingerprinted PII | `make audit-verify`, `make audit-tamper-demo` |
| Money/concurrency correctness | Possible but hard to test in low-code **(unverified — our assessment, no Microsoft source)** | Integer cents, row locks, property tests | refunds cumulative-reservation tests |
| Testing & change control | Solutions + Power Platform pipelines for ALM/CI-CD [[10]](https://learn.microsoft.com/en-us/power-platform/alm/pipelines). Testing is UI-level: Test Studio for canvas apps [[11]](https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/test-studio); Test Engine was deprecated April 2026 and Microsoft now points to Playwright samples [[12]](https://learn.microsoft.com/en-us/power-platform/important-changes-coming#deprecation-of-test-engine). No unit-test framework for app logic is documented **(unverified)** | Full unit/integration/property tests, CI on every push | `.github/workflows/ci.yml` |
| Document AI | AI Builder prebuilt invoice processing model [[13]](https://learn.microsoft.com/en-us/ai-builder/prebuilt-invoice-processing); runs consume AI Builder credits or Copilot Credits (see licensing notes) | Pluggable `Extractor`; prototype parses text-layer PDFs only | `foundation/extraction.py` — accuracy **not evaluated** |
| Hosting/ops/compliance | Microsoft-operated SaaS; Power Apps/Power Automate are in scope of Microsoft compliance offerings such as SOC 2 and ISO 27001 [[14]](https://learn.microsoft.com/en-us/compliance/regulatory/offering-soc-2) [[15]](https://learn.microsoft.com/en-us/compliance/regulatory/offering-iso-27001); Microsoft points to the Trust Center as authoritative [[16]](https://learn.microsoft.com/en-us/power-platform/admin/wp-compliance-data-privacy). (Corrected from "M365 compliance inherited": Power Platform has its own scope entries, not inheritance from M365.) | Customer must host, back up, monitor, pen-test | README "Honest limits" — Power Apps better |
| Marginal cost of tool N+1 | Per-user licensing (Power Apps Premium) or per-app / pay-as-you-go; per-app SKU is no longer sold to new customers through some channels (see licensing notes) [[17]](https://learn.microsoft.com/en-us/power-platform/admin/pricing-billing-skus) | Engineering + Devin time; shared foundation reused | `docs/evidence/` per-tool commits and diff sizes |

## Licensing and governance notes (checked 2026-10)
- **Power Apps Premium** (formerly "per user"): $20/user/month, or $12/user/month with a 2,000-seat minimum; unlimited
  apps and Power Pages sites for the user; accrues 250 MB Dataverse database + 2 GB file per license
  [[18]](https://www.microsoft.com/en-us/power-platform/products/power-apps/pricing) [[19]](https://learn.microsoft.com/en-us/power-platform/admin/powerapps-flow-licensing-faq).
- **Power Apps per app**: $5/user/app/month (one app or one Power Pages site, in one environment)
  [[19]](https://learn.microsoft.com/en-us/power-platform/admin/powerapps-flow-licensing-faq) [[20]](https://learn.microsoft.com/en-us/power-platform/admin/about-powerapps-perapp).
  Effective January 2, 2026 it is no longer available to new customers through some purchasing channels; existing
  customers can keep/renew, CSP is not affected [[17]](https://learn.microsoft.com/en-us/power-platform/admin/pricing-billing-skus)
  [[21]](https://www.microsoft.com/en-us/licensing/news/power-app-per-app-end-of-sale). It's no longer listed on the
  public pricing page [[18]](https://www.microsoft.com/en-us/power-platform/products/power-apps/pricing).
- **Power Apps pay-as-you-go**: $10 per active user/app/month via Azure
  [[22]](https://learn.microsoft.com/en-us/power-platform/admin/pay-as-you-go-meters).
- **AI Builder credits vs Copilot Credits**: from November 1, 2025, AI Builder features in apps/flows consume AI Builder
  credits first, then Copilot Credits; AI Builder capacity add-ons are renewal/true-up only for existing customers (who
  can renew until November 1, 2026) and new customers must buy Copilot Credits; licenses bought or renewed from
  November 1, 2026 get no seeded AI Builder credits; any AI Builder action makes a flow premium; 1 Copilot Credit = $0.01
  pay-as-you-go [[23]](https://learn.microsoft.com/en-us/ai-builder/administer-licensing)
  [[24]](https://learn.microsoft.com/en-us/ai-builder/credit-management).
- **Power Pages**: licensed per website per month by authenticated and anonymous users. Authenticated: $200 per pack of
  100 users/site/month; anonymous: $75 per 500 users/site/month
  [[25]](https://www.microsoft.com/en-us/power-platform/products/power-pages/pricing); pay-as-you-go $4 per active
  authenticated user/website/month (meter listed as preview) [[22]](https://learn.microsoft.com/en-us/power-platform/admin/pay-as-you-go-meters).
  Users with Power Apps Premium aren't counted against the meter [[22]](https://learn.microsoft.com/en-us/power-platform/admin/pay-as-you-go-meters).
- **Dataverse capacity**: a Power Apps Premium tenant gets a default of 20 GB database, 20 GB file and 2 GB log, plus
  per-license accruals; extra capacity is sold in 1 GB increments
  [[26]](https://go.microsoft.com/fwlink/?linkid=2085130) (Power Platform Licensing Guide, October 2026). Database
  add-on: $40/GB/month [[18]](https://www.microsoft.com/en-us/power-platform/products/power-apps/pricing). Capacity is
  tracked per tenant in the admin center [[27]](https://learn.microsoft.com/en-us/power-platform/admin/capacity-storage).
- **Managed Environments**: included with standalone Power Apps/Automate/Pages/Copilot Studio licenses; every user
  running an app in a managed environment needs a premium license (or allocated per-app capacity); from February 2027
  unlicensed users are blocked from opening apps there
  [[28]](https://learn.microsoft.com/en-us/power-platform/admin/managed-environment-licensing). Unmanaged developer
  environments are deprecated (enable Managed Environments before December 15, 2026)
  [[29]](https://learn.microsoft.com/en-us/power-platform/admin/managed-environment-overview).
- **DLP (data policies)**: connectors are classified Business / Non-Business / Blocked; new policies put connectors in
  Non-Business by default; an app or flow can't combine connectors from different groups; some connectors can't be
  blocked [[30]](https://learn.microsoft.com/en-us/power-platform/admin/dlp-connector-classification)
  [[31]](https://learn.microsoft.com/en-us/power-platform/admin/wp-data-loss-prevention).

## Recommendation shape
- **Build with Devin** where controls, money movement, complex rules or test coverage matter (KYC, refunds, AP, complaints).
- **Keep Power Apps** for simple departmental forms/lists owned by non-engineers and tightly bound to M365.
- **Complement**: Devin-built services can expose APIs that Power Apps/Automate call, so both coexist on Entra.

## Sources
All checked 2026-10.
1. https://learn.microsoft.com/en-us/power-apps/powerapps-overview
2. https://learn.microsoft.com/en-us/power-automate/create-business-process-flow
3. https://learn.microsoft.com/en-us/power-automate/business-process-flows-overview
4. https://learn.microsoft.com/en-us/power-platform/admin/security/authenticate-services
5. https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference
6. https://learn.microsoft.com/en-us/power-platform/admin/security-roles-privileges
7. https://learn.microsoft.com/en-us/power-platform/admin/field-level-security
8. https://learn.microsoft.com/en-us/power-automate/get-started-approvals
9. https://learn.microsoft.com/en-us/power-platform/admin/manage-dataverse-auditing
10. https://learn.microsoft.com/en-us/power-platform/alm/pipelines
11. https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/test-studio
12. https://learn.microsoft.com/en-us/power-platform/important-changes-coming#deprecation-of-test-engine
13. https://learn.microsoft.com/en-us/ai-builder/prebuilt-invoice-processing
14. https://learn.microsoft.com/en-us/compliance/regulatory/offering-soc-2
15. https://learn.microsoft.com/en-us/compliance/regulatory/offering-iso-27001
16. https://learn.microsoft.com/en-us/power-platform/admin/wp-compliance-data-privacy
17. https://learn.microsoft.com/en-us/power-platform/admin/pricing-billing-skus
18. https://www.microsoft.com/en-us/power-platform/products/power-apps/pricing
19. https://learn.microsoft.com/en-us/power-platform/admin/powerapps-flow-licensing-faq
20. https://learn.microsoft.com/en-us/power-platform/admin/about-powerapps-perapp
21. https://www.microsoft.com/en-us/licensing/news/power-app-per-app-end-of-sale
22. https://learn.microsoft.com/en-us/power-platform/admin/pay-as-you-go-meters
23. https://learn.microsoft.com/en-us/ai-builder/administer-licensing
24. https://learn.microsoft.com/en-us/ai-builder/credit-management
25. https://www.microsoft.com/en-us/power-platform/products/power-pages/pricing
26. https://go.microsoft.com/fwlink/?linkid=2085130 (Power Platform Licensing Guide PDF, October 2026 edition)
27. https://learn.microsoft.com/en-us/power-platform/admin/capacity-storage
28. https://learn.microsoft.com/en-us/power-platform/admin/managed-environment-licensing
29. https://learn.microsoft.com/en-us/power-platform/admin/managed-environment-overview
30. https://learn.microsoft.com/en-us/power-platform/admin/dlp-connector-classification
31. https://learn.microsoft.com/en-us/power-platform/admin/wp-data-loss-prevention
