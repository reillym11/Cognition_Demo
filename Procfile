api: cd backend && uv run uvicorn app.host.asgi:app --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1 --reload --reload-dir app
worker: cd backend && uv run python -m app.host.worker
mocks: cd backend && uv run uvicorn mocks.app:app --port 8090
web: cd web && pnpm dev
