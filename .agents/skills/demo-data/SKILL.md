---
name: demo-data
description: Reset, seed and verify the local demo (synthetic data only). Use when the demo state is broken or before a walkthrough.
---

# Demo data

- `make up` starts Postgres, mock OIDC and mocks. `make demo-reset` drops, migrates and seeds every tool (~25k KYC cases,
  ~100k transactions, ~8k complaints, flags, AP vendors/POs/invoice PDFs).
- All people, companies, emails (`example.com`) and bank numbers are synthetic (Faker, fixed seeds). Never load real data.
- Personas are in `infra/oidc/personas.json`; log in at http://localhost:5173 and pick a persona on the mock login page.
- After reseeding run `make audit-verify` to confirm every audit chain verifies.
