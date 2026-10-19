# Internal Tools Platform — Devin-built prototype

A working prototype that tests whether a regulated fintech can replace (or complement) Power Apps internal tools with
tools built by Devin on one shared platform. It is **not** a UI clone: the point is the controls underneath — one
login, server-side permissions with row and field scopes, a tamper-evident audit log, a shared maker-checker approval
primitive, policy-as-data, background jobs — and how cheaply each additional tool can be added on top.

Everything runs on localhost with **synthetic data only** (Faker, fixed seeds, `example.com`, fake bank numbers).

## What's in it

| Tool | What it shows |
|---|---|
| **KYC review** (~25k cases) | Server-side filter/sort/paging, claim races, SLA timers, four-eyes decisions (every case needs two people), senior review for high risk, audited auto-clear fast lane with versioned criteria + daily 2% QA sample, region row isolation, masked PII with audited reveal, 5-year retention class |
| **Refunds** (~100k transactions) | Integer cents, cumulative reservation under row lock (pending refunds count), threshold approval by a different person, velocity flag, idempotent execution, unknown-outcome reconciliation, processor fault injection, mock Teams notice |
| **Feature flags** (thin) | dev/staging/prod, % rollout + simple targeting, deterministic bucketing, explicit missing defaults, prod changes need a second person, full diff history, stale-flag report job |
| **Complaints** (~8k) | Reusable stage engine: per-stage required fields, checklists, SLAs, one-level regulatory branch to compliance review with separation of duties, root-cause taxonomy, KYC/refund links, aging dashboard, register CSV |
| **AP invoices** | PDF intake (upload + mock inbox) with validation/active-content rejection, text-layer field extraction with confidence, human verification, duplicate + vendor/PO match, tiered sequential approvals, call-back-verified bank changes (3 different people), audited SHA-256 payment batches |

Shared foundation (`backend/app/foundation/`): `auth` (OIDC + PKCE, opaque server sessions, CSRF, idle/absolute
timeouts), `authz` (deny-by-default; startup fails if a route lacks a permission), `datacls` (one register of sensitive
fields driving masking, log redaction, audit fingerprints, exports), `audit` (hash-chained, same-transaction, DB grants
block update/delete), `approvals`, `policy`, `jobs` (Postgres `SKIP LOCKED` queue), `notify` (outbox), `workflow`,
`files`, `extraction`, `exports`. Admin pages: audit explorer + chain verify, policies, jobs/dead letters, access matrix.

## Run it

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22 + pnpm 9.

```bash
make setup        # uv sync, pnpm install, playwright chromium, git hooks
make up           # Postgres :54320, mock Entra OIDC :8081 (docker compose)
make demo-reset   # migrate + seed all tools
make dev          # API :8000, worker, mocks :8090, web :5173
make e2e          # browser tests (10) against the running stack, in a second shell
```

Open http://localhost:5173, pick a role in the **Sign in as** dropdown and click **Sign in**. The app still runs
the real OIDC code + PKCE round trip against the mock Entra ID; the mock's page completes itself for the chosen role
(standard `login_hint`), so there is no second page. Each role has access no other role has:

| Role (dropdown) | Entra app role | Try |
|---|---|---|
| KYC Analyst | KYC.Analyst (US) | Claim and recommend a KYC case in the US region |
| KYC Senior Reviewer | KYC.SeniorReviewer | Make the second decision (four eyes), high-risk cases, QA sample |
| Compliance Admin | Compliance.Admin | KYC across regions, complaint compliance review, audit, policies |
| Support Agent | Support.Agent | Request a refund over $500 for any region |
| Support Contractor (EU) | Support.Contractor | Sees only EU merchants' refund transactions, PII masked |
| Finance Approver | Finance.Approver | Approve the refund (must be a different person) |
| Financial Controller | Finance.Controller + AP.Approver | Tier 2 invoice approval, final bank-change approval, refund reconciliation |
| AP Clerk | AP.Clerk | Upload or poll an invoice, verify fields, request a bank-detail change |
| AP Approver | AP.Approver | Tier 1 invoice approval, bank-change call-back |
| Complaints Handler | Complaints.Handler | Work a complaint through the stages |
| Engineer | Eng.Engineer | Create a flag, request a production change |
| Platform Admin | Platform.Admin | Approve the production flag change, jobs, access matrix |
| Auditor | Audit.Auditor | Read-only everywhere, audit explorer, evidence export |

`infra/oidc/personas.json` also holds four test-only accounts (`hidden`), which are not offered at sign-in: a second
KYC analyst, a second complaints handler, a product manager, and a user with a groups overage (more than 200 groups
and no app roles, which is refused). After editing personas run `python scripts/gen_login_page.py`.

To use the app from a single public URL (for example a preview link), start it with
`ITP_PUBLIC_BASE_URL=<url> ITP_OIDC_BROWSER_ISSUER=<url>/entra make dev`; the web server proxies `/entra` to the mock
Entra ID so the whole sign-in stays on that one address.

Useful commands: `make check` (everything CI runs), `make test`, `make audit-verify`, `make audit-tamper-demo`
(edits one audit row as superuser and shows verification fail), `make access-matrix`, `make new-tool name=<x>`.

## How it was built with Devin

- Direct-to-`main` commits (no PRs, by choice). Safety net: pre-push `make check`, CI on every push, self-review
  notes in `docs/evidence/self-review/`, a protected-path tick-off issue, and Devin Code Scans on `main`.
- `AGENTS.md` / `REVIEW.md` give every session the conventions and review checklist.
- Repo skills in `.agents/skills/` (`new-internal-tool`, `security-review`, `demo-data`) and the
  `!new-internal-tool` playbook (`docs/playbooks/new-internal-tool.md`) make tool N+1 repeatable.
- Non-engineer change requests: the **Internal tool change request** issue form (label `change-request`) is the
  stand-in for Teams; a Devin Automation picks those issues up. Teams was not installable in this tenant.
- Measurements: `docs/evidence/` — engineering measurement report: [`docs/evidence/measurement.md`](docs/evidence/measurement.md).
- UI: Microsoft Fluent UI v9 (`@fluentui/react-components`, MIT), laid out like Power Apps model-driven apps: grouped
  sitemap navigation, command bar, list views with filters, record pages with Summary / Audit history tabs, and a
  business-process-flow style stage bar for complaints. It matches the look, not the Power Apps maker experience.

## Honest limits

- **Localhost only.** Production needs managed Postgres with PITR, object storage with retention lock (WORM) for files
  and audit export, a real Entra app registration, secrets manager, TLS, monitoring/alerting, backups and DR tests.
  None of that is claimed here.
- **Audit is tamper-evident, not tamper-proof**: a DB superuser can rewrite rows; the hash chain only detects it.
- **Known gap (code scan, low):** the AP inbox poll takes one message at a time but keeps going until the inbox is
  empty, inside one transaction, so a flood of inbox messages keeps the single worker busy and holds the AP audit lock.
  Fix: cap messages per run and commit per message. Left open by choice for the prototype.
- **Teams is mocked** (local webhook receiver). **Processor and AP inbox are mocks.**
- **AP extraction** parses the text layer of synthetic PDFs. No OCR, no accuracy claim vs AI Builder on real invoices.
- **Where Power Apps stays better**: citizen-developer speed for simple forms/lists
  ([overview](https://learn.microsoft.com/en-us/power-apps/powerapps-overview)), visual designers non-engineers can
  edit, built-in M365/Dataverse integration and Microsoft-operated hosting/compliance
  ([compliance](https://learn.microsoft.com/en-us/power-platform/admin/wp-compliance-data-privacy)); links checked 2026-10.
  Sources for every claim: `docs/power-apps-comparison.md`.
