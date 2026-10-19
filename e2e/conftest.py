"""Browser tests against a running `make dev` (web :5173, API :8000, mock Entra :8081)."""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

WEB = os.environ.get("ITP_WEB_URL", "http://localhost:5173")
_PERSONAS = json.loads((Path(__file__).resolve().parents[1] / "infra/oidc/personas.json").read_text())[
    "personas"
]
OFFERED = {p["username"] for p in _PERSONAS if not p.get("hidden")}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: browser tests (run via make e2e)")


def start_login(page: Page, persona: str) -> None:
    """Real OIDC code+PKCE round trip; the mock Entra page completes itself from login_hint."""
    page.goto(f"{WEB}/login")
    if persona in OFFERED:
        page.get_by_label("Sign in as").select_option(persona)
        page.get_by_role("link", name="Sign in", exact=True).click()
    else:  # test-only personas are not offered in the dropdown
        page.goto(f"{WEB}/api/auth/login?login_hint={persona}")
    page.wait_for_url(
        lambda u: u.startswith(WEB) and "/api/auth/" not in u and u.rstrip("/") != f"{WEB}/login"
    )


def login(page: Page, persona: str) -> None:
    start_login(page, persona)
    expect(page.get_by_role("link", name="Internal Tools")).to_be_visible()


@pytest.fixture
def as_persona(page: Page):
    def _go(persona: str) -> Page:
        login(page, persona)
        return page

    return _go
