#!/usr/bin/env bash
# Runs once when the Codespace (or dev container) is created.
set -euo pipefail
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
make setup
docker compose pull --quiet || true
echo "Ready. Run: make demo-reset && make dev   (then open the forwarded port 5173)"
