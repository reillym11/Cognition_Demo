# Applications by Devin

A working prototype that tests whether a fintech can replace or complement its Power Apps internal tools with tools
built by Devin. Five tools run on one shared platform: login, server-side permissions, audit log, approvals,
policies and background jobs are written once and reused by every tool.

Everything runs locally with **synthetic data only**.

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, uv |
| Database | PostgreSQL 16 (also the job queue) |
| Frontend | React 18, TypeScript, Vite, TanStack Query, Microsoft Fluent UI v9, pnpm |
| Identity | OIDC code flow + PKCE against a mock Microsoft Entra ID (`mock-oauth2-server`) |
| Tests | pytest (173 backend tests, real Postgres), Playwright browser tests |
| Tooling | Docker Compose, GitHub Actions CI, GitHub Codespaces dev container |

## The tools

| Tool | What it shows |
|---|---|
| **KYC review** (~25k cases) | Review queue with SLA timers, four-eyes decisions, senior review for high risk, an audited auto-clear lane with a QA sample, region-limited access, masked PII with audited reveal |
| **Refunds** (~100k transactions) | Money in integer cents, a second person above the approval threshold, velocity flags, safe retries and reconciliation when the processor's answer is unknown |
| **Feature flags** | Dev, staging and production environments, percentage rollout and targeting, production changes need a second person, full change history |
| **Complaints** (~8k) | Stage-by-stage case flow with required fields and SLAs, a compliance review branch, aging summary on the home page |
| **AP invoices** | PDF validation and field extraction, human verification, duplicate and PO matching, tiered approvals, bank-detail changes that need three different people |

The shared platform lives in `backend/app/foundation/`. Each tool is a package in `backend/app/tools/<tool>/` with a
manifest that declares its permissions, roles, navigation, policies and sensitive fields.

Platform rules that every tool inherits:
- Every API route must declare a permission or the server refuses to start. The UI never decides access.
- Every change and every sensitive read is written to a hash-chained audit log in the same transaction.
- Anything that needs a second person goes through one approvals module: no self-approval, reasons required.
- Thresholds and criteria are versioned policies, and changing one needs its own approval.

## Run it

### In GitHub Codespaces (nothing to install)

1. On the repo page click **Code > Codespaces > Create codespace on main** (4-core machine). The first start takes a
   few minutes.
2. In the terminal run `make demo-reset && make dev`.
3. In the **Ports** tab open port **5173**, pick a role in **Sign in as** and click **Sign in**.

Stop the Codespace when you are done.

### On your own machine

Requires Docker, [uv](https://docs.astral.sh/uv/), Node 22 and pnpm 9.

```bash
make setup        # install Python and web dependencies
make demo-reset   # start Postgres, create and seed the database
make dev          # API :8000, worker, mocks :8090, web :5173
```

Open http://localhost:5173, pick a role and sign in.

### Roles

Each role can do something no other role can.

| Role | Try |
|---|---|
| KYC Analyst | Claim and recommend a KYC case in the US region |
| KYC Senior Reviewer | Make the second decision on a case, handle high-risk cases, review the QA sample |
| Compliance Admin | See KYC across regions, sign off complaints, approve policy changes |
| Support Agent | Request a refund over $500 |
| Outsourced Support (EU) | See only EU merchants' refunds, with customer details masked |
| Financial Controller | Approve refunds and tier 2 invoices, give final approval on bank-detail changes |
| AP Clerk | Verify extracted invoice fields, request a bank-detail change |
| AP Approver | Approve tier 1 invoices, confirm bank changes by call-back |
| Complaints Handler | Work a complaint through its stages |
| Engineer | Create a flag and request a production change |
| Platform Admin | Approve production flag changes, manage background jobs |
| Auditor | Read everything, verify the audit log, export evidence |

### Useful commands

| Command | Does |
|---|---|
| `make check` | Everything CI runs: lint, type checks, backend tests, API client drift, no-dash check |
| `make e2e` | Browser tests against a running `make dev` |
| `make audit-verify` | Verify every audit hash chain |
| `make audit-tamper-demo` | Edit one audit row as a superuser and show verification fail |
| `make new-tool name=<x>` | Scaffold a new tool package |

## How it was built with Devin

- Commits go straight to `main`. The safety net is `make check` before every push, CI on every push, self-review
  notes for protected code (`docs/evidence/self-review/`) and Devin code scans.
- `AGENTS.md` and `REVIEW.md` give every Devin session the same rules and review checklist.
- Repo skills (`.agents/skills/`) and the `!new_internal_tool` playbook let a fresh session build the next tool.
- Change requests from non-engineers use a GitHub issue form (label `change-request`) that a Devin Automation picks
  up. This stands in for Teams, which could not be installed in this tenant.
- The UI uses Microsoft Fluent UI v9 in a Power Apps model-driven layout: grouped navigation, command bar, list views,
  record pages with Summary and Audit history tabs, and a stage bar for complaints.
- Measurements: [`docs/evidence/measurement.md`](docs/evidence/measurement.md). Power Apps comparison with sources:
  [`docs/power-apps-comparison.md`](docs/power-apps-comparison.md).

## Honest limits

- **Not production.** Hosting, managed Postgres with backups, secrets, monitoring and a real Entra app registration
  are not built.
- **Audit is tamper-evident, not tamper-proof.** A database superuser can rewrite rows; the hash chain only detects
  it. Production needs write-once storage.
- **External systems are mocked:** Entra ID, Teams, the payment processor and the AP inbox.
- **AP extraction is untested on real invoices.** It reads the text layer of synthetic PDFs, with no OCR.
- **Power Apps stays better** for citizen-developer speed, visual editing by non-engineers, built-in Microsoft 365
  integration and Microsoft-operated hosting and compliance.
