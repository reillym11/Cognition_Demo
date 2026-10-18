---
name: security-review
description: Self-review checklist for changes to protected paths (auth, authz, audit, approvals, policy, datacls, files, migrations). Use before pushing any commit that touches PROTECTED_PATHS.
---

# Security self-review (direct-to-main)

1. `git diff --name-only origin/main | grep -Ef PROTECTED_PATHS` — if anything matches, continue.
2. Check against `REVIEW.md`: deny-by-default, server-side checks, no client-only auth, reasons on decisions,
   audit in the same transaction, no cleartext PII in audit/logs, no self-approval paths, idempotent decisions.
3. Add or update a test that would fail if the control were removed.
4. Write `docs/evidence/self-review/<date>-<slug>.md` with: files changed, controls affected, tests proving them, residual risk.
5. Open (or comment on) the "Protected path changes" GitHub issue with the commit link so the owner can tick it off.
