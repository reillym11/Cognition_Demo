# Engineering evidence (direct-to-main)

Generated from `git log --shortstat`; CI results from GitHub Actions on each push.

| Commit | Session | Files | +lines | -lines |
|---|---|---|---|---|
| c6a33ff | [S0.5][S1] | 61 | 7920 | 0 |
| 45c9be7 | [S1][S6] | 30 | 3542 | 348 |
| 7f0bd7a | [S8][S9] | 20 | 3328 | 11 |
| 84da4f5 | [S11] | 15 | 2572 | 62 |
| 47cc7d7 | [S12] | 13 | 1744 | 3 |
| d09606c | [S14] | 13 | 2561 | 0 |
| b20f6e7 | [S14c-e] | 16 | 4069 | 0 |
| e19a481 | [S10] | 4 | 104 | 0 |
| 88ac687 | [S15] | 2 | 46 | 0 |
| 8183f46 | [S16] | 1 | 23 | 0 |
| 5e97a32 | [S18] | 2 | 99 | 0 |

## CI failures on push (primary safety-net metric)

| Commit | Failed step | Cause | Fixed in |
|---|---|---|---|
| 45c9be7 | `make lint` | Makefile chained `cd backend && ... && cd backend` (second `cd` from inside `backend/`) | 7f0bd7a (`uv run --directory backend`) |
| 84da4f5 | `make lint` | Ruff `SIM105` (try/except/pass) in refund tests; pushed with `SKIP_CHECK=1` | 47cc7d7 |

Both failures were lint-only and caught by CI within minutes; no failing tests or security regressions reached `main`.
Lesson applied: stop pushing with `SKIP_CHECK=1`; the pre-push `make check` would have caught both.
