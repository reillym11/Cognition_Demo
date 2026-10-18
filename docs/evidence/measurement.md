# Engineering measurement report

Five internal tools (KYC, refunds, flags, complaints, AP invoices) were built with Devin on one shared foundation, to
compare against Power Apps. Every number here comes from the repo or GitHub. Commands are listed so anyone can re-run
them. Snapshot: `main` at `15d0940` (13 commits), measured 2026-10-18.

**Not measured here:** ACUs or wall-clock effort per session, how many sessions there were (several commits fold several
sessions together, e.g. `[S14c-e]`), human review time, runtime performance, and test pass/fail on this machine (tests
were collected, not run; CI results are below). Commit timestamps record when commits were pushed (all 13 between
22:49 and 23:30 UTC on 2026-10-18), not how long the work took.

## Key numbers

| # | Metric | Value |
|---|---|---|
| 1 | New hand-written lines per tool (backend + tests + web + migration) | **mean 1,389**, median 1,374, range 952 (flags) to 1,923 (AP) |
| 2 | Share of directly used code that is new to each tool (the rest is reused foundation) | **29–41%** (so 59–71% is reused); the full runtime foundation is 3,902 lines |
| 3 | CI runs on `main` | **12 runs: 10 passed, 2 failed** (both `make lint`, each fixed by the next push) |
| 4 | Tests | **78 backend** (61 tool + 17 foundation) + **10 e2e** (Playwright) |
| 5 | Commits touching `PROTECTED_PATHS` | **9 of 13**; **2** have a self-review note; **0** ticked off in the review issues |

## 1. Per-commit table

Method: `git log --reverse --numstat main`. Each file is assigned to an area by its path: `backend/app/tools/<key>/`,
`web/src/tools/<key>/` and `backend/migrations/versions/NNNN_<key>.py` → that tool; `backend/app/foundation/` →
foundation; `web/src/api/{openapi.json,schema.d.ts}` → generated client; `web/src/{shell,ui}` and web config →
web shell/UI; `uv.lock`/`pnpm-lock.yaml` → lockfiles; `docs/`, `*.md` → docs. The areas column shows lines added per area.

| Commit | Session | Files | +lines | −lines | Areas touched (+lines) |
|---|---|---|---|---|---|
| [c6a33ff](https://github.com/reillym11/Cognition_Demo/commit/c6a33ff93746d991c1278279f77cbb1b65bc0cf5) | [S0.5][S1] | 61 | 7,920 | 0 | web shell/UI 3,123; foundation 1,918; lockfiles 1,520; foundation tests 271; host 259; infra/CI/tooling 226; migration 0001 190; mocks 185; other backend 155; client.ts 43; docs 13 |
| [45c9be7](https://github.com/reillym11/Cognition_Demo/commit/45c9be7dacb552f7715f2a8cdf95c2556b4c75d0) | [S1][S6] | 30 | 3,542 | 348 | generated client 1,867; web shell/UI 692; foundation 579; migration 0001 177; infra/CI 73; docs 61; host 41; foundation tests 32; mocks 20 |
| [7f0bd7a](https://github.com/reillym11/Cognition_Demo/commit/7f0bd7a05c9fabfd9e3948bc044172475082ca99) | [S8][S9] | 20 | 3,328 | 11 | generated client 1,788; **kyc 1,520**; Makefile/conftest/test fixtures 19 |
| [84da4f5](https://github.com/reillym11/Cognition_Demo/commit/84da4f568609978d57f3ea8cc9419ab771f6f16a) | [S11] | 15 | 2,572 | 62 | **refunds 1,375**; generated client 1,193; mocks 3; pyproject 1 |
| [47cc7d7](https://github.com/reillym11/Cognition_Demo/commit/47cc7d7b37fe807e1ca49fe36afc23d1e66103d4) | [S12] | 13 | 1,744 | 3 | **flags 952**; generated client 790; refunds 2 (lint fix) |
| [d09606c](https://github.com/reillym11/Cognition_Demo/commit/d09606c4da51014da3d356ac0f44bee4a775b7f7) | [S14] | 13 | 2,561 | 0 | generated client 1,287; **complaints 1,174**; foundation 100 (`workflow.py`) |
| [b20f6e7](https://github.com/reillym11/Cognition_Demo/commit/b20f6e753dad9167edd454e95470f8068f74f0db) | [S14c-e] | 16 | 4,069 | 0 | **ap 1,923**; generated client 1,894; foundation 252 (`files.py` 110, `extraction.py` 131, `money.py` 11) |
| [e19a481](https://github.com/reillym11/Cognition_Demo/commit/e19a481ecdf10268127cdd1d5ba9dbd45dcfc093) | [S10] | 4 | 104 | 0 | docs/skills 104 (`.agents/skills/`, playbook) |
| [88ac687](https://github.com/reillym11/Cognition_Demo/commit/88ac6873802b9121d08c347c5fbef6fc23dc36a9) | [S15] | 2 | 46 | 0 | `.github/ISSUE_TEMPLATE` 46 |
| [8183f46](https://github.com/reillym11/Cognition_Demo/commit/8183f461a31a9585447f485583f0cdc26dc27ef5) | [S16] | 1 | 23 | 0 | docs (self-review) 23 |
| [5e97a32](https://github.com/reillym11/Cognition_Demo/commit/5e97a3292eb698942dde6a9105efec10d6e69163) | [S18] | 2 | 99 | 0 | docs (README, Power Apps comparison) 99 |
| [ced183a](https://github.com/reillym11/Cognition_Demo/commit/ced183a367af09b1d410539903a28279a1f5374c) | [S18] | 1 | 27 | 0 | docs (`sessions.md`) 27 |
| [15d0940](https://github.com/reillym11/Cognition_Demo/commit/15d094004139ff7ac33fa85dfe060054029fb026) | [S17] | 16 | 648 | 460 | web shell/UI + config 363; e2e 95; generated client 94; lockfiles 31; foundation 27; docs 24; foundation tests 7; CI 3; host 3 |
| **Total** | | | **26,683** | **884** | |

Notes:
- `docs/evidence/sessions.md` lists 11 commits. It is missing `ced183a` (the commit that added it) and `15d0940`.
- AGENTS.md says "Foundation changes are their own commits". Two tool commits broke this rule by putting new
  foundation modules in the same commit as the tool: `d09606c` (workflow) and `b20f6e7` (files/extraction). The KYC
  commit `7f0bd7a` also changed shared test fixtures and the Makefile.
- About a third of all added lines (8,956 of 26,683) are the generated OpenAPI client, which is regenerated in full on
  every API change. Lockfiles add another 1,551.

## 2. Per-tool totals: new code vs reused foundation

Method A (history): lines each tool's paths gained, from `git log --numstat`. Method B (current files): `wc -l` (physical
lines, blank lines included) of the files in `git ls-files` at `15d0940`. The two methods agree to within 3 lines for
every tool. "Directly used foundation" means the `backend/app/foundation/*.py` modules the tool imports outside its
tests (`from app.foundation…`), plus the pieces every tool depends on without importing them: `auth.py` (302),
`backend/app/host` (287), and the web shell, UI kit and API client (`web/src/shell`, `web/src/ui`,
`web/src/api/client.ts`: 707). Together these are 1,296 lines.

| Tool | Backend (excl. tests) | Tests | Web | Migration | **New hand-written** | Generated client added | Foundation added in tool commit | Foundation modules imported | Directly used foundation lines | **New share** |
|---|---|---|---|---|---|---|---|---|---|---|
| kyc | 958 | 272 | 185 | 105 | **1,520** | 1,788 | 0 | 11 | 1,397 + 1,296 = 2,693 | **36%** |
| refunds | 845 | 262 | 182 | 85 | **1,374** | 1,193 | 0 | 14 | 1,544 + 1,296 = 2,840 | **33%** |
| flags | 601 | 139 | 136 | 76 | **952** | 790 | 0 | 8 | 1,009 + 1,296 = 2,305 | **29%** |
| complaints | 716 | 182 | 206 | 70 | **1,174** | 1,287 | 100 (`workflow`) | 9 | 930 + 1,296 = 2,226 | **35%** |
| ap | 1,319 | 242 | 211 | 151 | **1,923** | 1,894 | 252 (`files`, `extraction`, `money`) | 12 | 1,425 + 1,296 = 2,721 | **41%** |
| **Total / mean** | 4,439 / 888 | 1,097 / 219 | 920 / 184 | 487 / 97 | **6,943 / 1,389** | 6,952 / 1,390 | 352 / 70 | | | |

New share = new hand-written ÷ (new hand-written + directly used foundation). AP has more backend code because it
includes a test PDF generator (`pdfgen.py`, 64 lines).

Shared foundation now (method B):

| Part | Lines | At `45c9be7` (before the first tool) |
|---|---|---|
| `backend/app/foundation/` (24 files) | 2,692 | 2,325 |
| `backend/app/host/` | 287 | 289 |
| `backend/migrations/versions/0001_foundation.py` | 216 | 216 |
| `web/src/shell` + `web/src/ui` + `web/src/api/client.ts` | 707 | 707 |
| **Runtime foundation** | **3,902** | **3,537** |
| Supporting: `backend/mocks` 203, `backend/tests` 203, `backend/testing.py` + `conftest.py` 102, `e2e/` 95 | 603 | |
| Generated client (`openapi.json` + `schema.d.ts`), not hand-written | 8,767 | |

Answer to the key question: the foundation was built once, before the first tool (3,537 runtime lines). The five tools
then added 6,943 lines of their own code and only 352 more lines of foundation, 5% of the tool code. Each tool's new
code is 24–49% of the size of the whole runtime foundation (20–33% of foundation + tool together). Measured against only the foundation code that tool
actually uses, new code is 29–41%, so roughly two thirds of what each tool runs on is reused. All five web pages
import the same four shared modules (`api/client`, `shell/me`, `ui/kit`, `tools/registry`). No tool commit changed the
host or shell to register itself: backend tools are found by scanning `app/tools`, and web routes by
`import.meta.glob`.

## 3. CI history

Source: `gh run list --limit 100`. There is one workflow (`ci`: lint, typecheck, pytest on Postgres, OpenAPI drift,
gitleaks, pip-audit, plus a protected-paths job). It returned 12 runs. `c6a33ff` has no run because CI was added in
`45c9be7`.

| Commit | Conclusion | Duration |
|---|---|---|
| 45c9be7 | **failure** | 30 s |
| 7f0bd7a | success | 1 m 38 s |
| 84da4f5 | **failure** | 29 s |
| 47cc7d7 | success | 2 m 04 s |
| d09606c | success | 2 m 17 s |
| b20f6e7 | success | 1 m 35 s |
| e19a481 | success | 2 m 00 s |
| 88ac687 | success | 2 m 15 s |
| 8183f46 | success | 2 m 10 s |
| 5e97a32 | success | 2 m 14 s |
| ced183a | success | 2 m 11 s |
| 15d0940 | success | 1 m 47 s |

Pass rate: 10 of 12 (83%). Median successful run: 2 m 07 s. Duration = `updatedAt − startedAt`.

Failures (from `gh run view --log-failed`; these match `sessions.md`):

| Commit | Failed step | Cause (from the log) | Fixed in | `main` red for |
|---|---|---|---|---|
| 45c9be7 | `make lint` | `cd backend && … && cd backend …` → `cd: backend: No such file or directory` (Makefile:55) | 7f0bd7a (Makefile paths, `uv run --directory backend`) | ~6 min (22:51 → 22:57) |
| 84da4f5 | `make lint` | Ruff `SIM105` (try/except/pass → `contextlib.suppress`) in `test_refunds.py`; pushed with `SKIP_CHECK=1` per `sessions.md` | 47cc7d7 ("fix SIM105 lint") | ~3 min (23:00 → 23:03) |

Neither failure was a test, typecheck or security failure. Both would have been caught by the pre-push `make check`
had it not been skipped or broken.

## 4. Test inventory

Method: `uv run pytest --collect-only -q` in `backend/` (collection only, no database needed; the tests were not run
here). For e2e: `uv run pytest ../e2e -m e2e --collect-only -q`.

| Suite | File | Tests collected | Test lines |
|---|---|---|---|
| Foundation | `backend/tests/test_foundation.py` | 17 | 203 |
| KYC | `backend/app/tools/kyc/tests/test_kyc.py` | 15 | 272 |
| Refunds | `backend/app/tools/refunds/tests/test_refunds.py` | 15 | 262 |
| Flags | `backend/app/tools/flags/tests/test_flags.py` | 9 | 139 |
| Complaints | `backend/app/tools/complaints/tests/test_complaints.py` | 9 | 182 |
| AP invoices | `backend/app/tools/ap/tests/test_ap.py` | 13 | 242 |
| **Backend total** | | **78** (61 tool, mean 12.2 per tool) | 1,300 |
| e2e (Playwright, Chromium) | `e2e/test_platform.py` | **10** (6 functions; one is parametrised over 5 personas, one per tool) | 61 (+34 conftest) |

What the e2e suite covers: real OIDC code+PKCE login through mock Entra for each persona, nav vs server-side 403, KYC
PII masked in the list, groups-overage user refused at login, auditor can read the audit log but not approve, and
logged-out redirect. CI does not run e2e. `make check` excludes it, and it needs a running `make dev`. `test_inbox_poll`
(AP) skips when the mocks are not running.

## 5. Protected-path changes

Method: each commit's `git show --name-only` matched against the regexes in `PROTECTED_PATHS`. Notes were checked in
`docs/evidence/self-review/`. Review records are issue #1 (opened by the CI protected-paths job) and issue #2 (the
manual owner log).

| Commit | Protected files | Self-review note | Issue tick-off |
|---|---|---|---|
| c6a33ff | foundation `auth`, `authz`, `audit`, `approvals`, `policy`, `datacls`; `migrations/` (env, 0001); `infra/` (oidc, postgres init) | **none** | #2 unticked (pre-CI, not in #1) |
| 45c9be7 | `.github/workflows/ci.yml`; foundation `auth`, `authz`, `audit`, `approvals`, `policy`; 0001 | **none** | #1, #2 unticked |
| 7f0bd7a | `migrations/env.py`, 0002_kyc | **none** | #1 unticked (missing from #2) |
| 84da4f5 | 0003_refunds | **none** | #1, #2 unticked |
| 47cc7d7 | 0004_flags | **none** | #1, #2 unticked |
| d09606c | 0005_complaints | **none** (`workflow.py` is not a protected path) | #1, #2 unticked |
| b20f6e7 | `foundation/files.py`, 0006_ap | `2026-10-17-files-extraction.md` (added afterwards in 8183f46) | #1, #2 unticked |
| 88ac687 | `.github/ISSUE_TEMPLATE/*` | **none** | #1 unticked (missing from #2) |
| 15d0940 | `.github/workflows/ci.yml`, `foundation/authz.py` | `2026-10-18-dependency-upgrades.md` (same commit) | #1 unticked (missing from #2) |

9 of 13 commits touched protected paths; 2 of 9 have a self-review note; 0 of 9 are ticked. The biggest security
surface (`c6a33ff`, `45c9be7`: auth, authz, audit, approvals) has no self-review note. Every tool commit is a
protected-path change, because each tool adds a migration under `backend/migrations/`.

## 6. What the next 10 tools would cost

The estimate scales items 1–2 linearly. Assumptions: the next tools are a similar mix to these five (thin
flags-like to AP-like); they reuse the current foundation unchanged unless they need a new primitive; the
generated-client approach and test conventions stay the same.

| Item | Per tool (observed) | 10 tools (estimate) |
|---|---|---|
| New hand-written lines | mean 1,389 (952–1,923): backend 888, tests 219, web 184, migration 97 | **~13,900** (9,500–19,200) |
| New foundation lines | 2 of 5 tools needed a primitive (100, 252); mean 70 | **~0–1,000**, as separate protected commits with self-review |
| Generated client lines (regenerated, not reviewed by hand) | mean 1,390 | ~13,900; `openapi.json` + `schema.d.ts` would grow from 8.8k to ~23k lines |
| Backend tests | mean 12.2 | **~120** |
| e2e | 1 persona case per tool today | ≥10 cases (plus one primary-flow test per tool, which today's suite does not have) |
| Migrations / protected-path reviews | 1 each | 10 migrations (0007–0016) → 10 self-review notes + tick-offs; more if personas/roles change (`infra/oidc/personas.json` is protected) |
| CI time per push | median 2 m 07 s | will grow with the test count; not projected |
| ACUs / elapsed time per tool | not measured here | not measured here |

Even at the high end, 10 more tools add less hand-written code (19.2k) than the five already built plus their
foundation and shell (~11k), because no new login, roles, audit, approvals or UI kit is needed. The main risks to the
estimate are a tool that needs a new kind of primitive (for example scheduling with calendars, or a document editor),
and the review load from protected-path changes, which grows with every tool.

## 7. Building future tools in parallel (plan only, not done)

One tool per Devin session, started from the `!new-internal-tool` playbook / `.agents/skills/new-internal-tool`, with a
coordinating session (or a Devin workflow) handing out assignments.

1. **Scope per session (AGENTS.md).** A tool session edits only `backend/app/tools/<key>/`, `web/src/tools/<key>/`,
   `e2e/test_<key>*.py`, its one migration, and `docs/` (including its own `docs/evidence/self-review/<session>.md`).
   The backend registry scan and `import.meta.glob` mean no host or shell edits. If a tool needs foundation or
   `infra/` changes, the session stops and asks. Those changes go in their own commit from one foundation session,
   land first, and are reviewed as protected-path changes.
2. **Shared files that will conflict, and how to handle each:**
   - *Migrations:* Alembic revisions form a linear chain (`0006` has `down_revision = "0005"`). The coordinator reserves
     numbers up front (tool A = 0007, B = 0008, …) and writes them in the assignment. On rebase, each session sets
     `down_revision` to the current head on `main` before pushing. A second head is never pushed; `alembic heads` must
     show exactly one.
   - *Generated client:* never hand-merge `web/src/api/openapi.json` / `schema.d.ts`. After `git pull --rebase`, take
     `main`'s version, run `make openapi`, and commit the regenerated files. `make openapi-check` in CI catches drift.
   - *Personas/roles:* new app roles need entries in `infra/oidc/personas.json` (protected). Batch these in one
     foundation/infra commit ahead of the tool sessions, or have the coordinator apply them one at a time.
   - *Lockfiles:* tool sessions should not add dependencies. Any dependency change is a separate commit.
3. **Before every push:** `git pull --rebase`, regenerate the client, then `make check` through the pre-push hook
   (`make hooks`). Never use `SKIP_CHECK=1`; both CI failures so far came from skipping or bypassing this gate. If `main`
   is red, every session stops and the fixing session goes first.
4. **Attribution and review:** commit prefix `[S<id>]` with a single session id per commit (avoid folding several
   sessions together as `[S14c-e]` does), one self-review note per session, and the CI protected-paths job adds each
   migration to issue #1 for owner tick-off.
5. **Measurement:** re-run the commands in this report after each batch to check new lines per tool and foundation
   reuse against the estimate in section 6.

## Commands used

```bash
git log --reverse --numstat --format='@@%H|%s' main          # items 1, 2 (method A), 5
git ls-files <paths> | xargs wc -l                           # item 2 (method B)
grep -rhE 'from app\.foundation' backend/app/tools/<key>     # foundation modules imported per tool
gh run list --limit 100 --json name,headSha,conclusion,startedAt,updatedAt
gh run view <id> --log-failed                                # item 3
cd backend && uv run pytest --collect-only -q                # item 4
uv run pytest ../e2e -m e2e -p no:cov --collect-only -q
gh issue view 1; gh issue view 2                             # item 5
```
