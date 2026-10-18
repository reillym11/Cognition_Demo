# S0.5 de-risking spike

Run on the Devin VM (8 vCPU, Postgres 16 in Docker) before S1. Throwaway scripts; results only.

| # | Mechanism | Result | Detail | Plan change |
|---|---|---|---|---|
| 1 | Mock OIDC issuing Entra-shaped claims | **Pass** | `ghcr.io/navikt/mock-oauth2-server:2.1.10` auth-code flow returned an ID token containing custom `roles`, `oid`, `tid`, `preferred_username` and a `_claim_names.groups` overage marker passed through the login form's `claims` field. | Use a custom `loginPagePath` with persona buttons so demos and e2e tests don't type JSON. |
| 2 | Audit hash chain, 50 concurrent writers × 20 events | **Pass** | 1,000 rows, chain verified, 0.82 s total, using `pg_advisory_xact_lock(hashtext(chain))` inside the business transaction. | None. One chain per tool. |
| 3 | Refund reservation under 20 concurrent $400 requests on a $1,000 capture, $500 cumulative threshold | **Pass** | `SELECT … FOR UPDATE` on the transaction row: 1 executed, 1 sent to approval (cumulative incl. pending > $500), 18 rejected as over-capture. | None. Pending refunds count toward the cumulative total. |
| 4 | OpenAPI → TypeScript client | **Pass** (verified in S1) | `openapi-typescript` + `openapi-fetch`; CI fails if `web/src/api/schema.d.ts` drifts from `make openapi`. | None. |
| 5 | 100k-row seed via `COPY` | **Pass** | 100,000 rows in 0.11 s (single table, fixed RNG seed 42). | `make demo-reset` reseeds from scratch instead of restoring a dump; the dump step isn't needed. |

Jobs queue decision (deferred to this spike): a small custom `SELECT … FOR UPDATE SKIP LOCKED` worker (~150 lines) instead of `procrastinate`, so the queue table doubles as the transactional outbox and job-initiated mutations share the audit helper.
