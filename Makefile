# One entry point for both toolchains. Run `make help`.
SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(HOME)/.local/node/bin:$(PATH)
UV := cd backend && uv run
OWNER_URL ?= postgresql+psycopg://itp_owner:itp_owner@localhost:54320/itp
TEST_OWNER_URL ?= postgresql+psycopg://itp_owner:itp_owner@localhost:54320/itp_test

.PHONY: help setup up down migrate migrate-test seed demo-reset dev api worker mocks web check lint typecheck test test-fast e2e openapi audit-verify audit-tamper-demo access-matrix new-tool hooks security

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-20s %s\n", $$1, $$2}'

setup: ## install deps (uv + pnpm + playwright chromium) and git hooks
	cd backend && uv sync
	cd web && pnpm install --frozen-lockfile
	cd backend && uv run playwright install chromium
	$(MAKE) hooks

hooks: ## install the pre-push gate
	git config core.hooksPath scripts/githooks

up: ## start Postgres + mock OIDC (docker compose)
	docker compose up -d --wait

down:
	docker compose down

migrate: ## apply migrations to the dev DB
	cd backend && ITP_OWNER_DATABASE_URL=$(OWNER_URL) uv run alembic upgrade head

migrate-test:
	cd backend && ITP_OWNER_DATABASE_URL=$(TEST_OWNER_URL) uv run alembic upgrade head

seed: ## load deterministic synthetic data (25k KYC, 100k transactions, ...)
	$(UV) python -m app.host.cli seed

demo-reset: ## drop + recreate dev DB, migrate, seed (target < 60 s)
	$(UV) python -m app.host.cli reset-db
	$(MAKE) migrate
	$(MAKE) seed

dev: up ## run api, worker, mocks and web together
	cd backend && uv run honcho -d .. -f Procfile start

api:
	$(UV) uvicorn app.host.asgi:app --port 8000 --reload
worker:
	$(UV) python -m app.host.worker
mocks:
	$(UV) uvicorn mocks.app:app --port 8090
web:
	cd web && pnpm dev

lint: ## ruff + eslint
	$(UV) ruff check . && $(UV) ruff format --check .
	cd web && pnpm lint

typecheck: ## mypy + tsc
	$(UV) mypy
	cd web && pnpm typecheck

test: migrate-test ## backend unit + integration + property tests (real Postgres)
	$(UV) pytest --cov --cov-report=term-missing:skip-covered

openapi: ## regenerate the TypeScript API client from FastAPI's OpenAPI schema
	$(UV) python -m app.host.cli openapi > ../web/src/api/openapi.json
	cd web && pnpm exec openapi-typescript src/api/openapi.json -o src/api/schema.d.ts

openapi-check: openapi ## fail if the generated client drifted
	git diff --exit-code -- web/src/api/

security: ## dependency + secret scanning
	$(UV) pip-audit --strict --progress-spinner off || true
	cd web && pnpm audit --audit-level high || true

check: lint typecheck test openapi-check ## everything CI runs (except e2e)

e2e: ## browser tests (needs `make dev` running in another shell)
	$(UV) pytest ../e2e -m e2e -p no:cov

audit-verify: ## verify every audit hash chain
	$(UV) python -m app.host.cli audit-verify

audit-tamper-demo: ## modify one audit row as DB superuser, then show verification failing
	$(UV) python -m app.host.cli audit-tamper-demo

access-matrix: ## regenerate docs/evidence/access-matrix.md
	$(UV) python -m app.host.cli access-matrix > ../docs/evidence/access-matrix.md

new-tool: ## scaffold a tool: make new-tool name=my_tool
	$(UV) python -m app.host.cli new-tool $(name)
