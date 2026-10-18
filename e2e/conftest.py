"""Browser tests against a running `make dev` (web :5173, API :8000, mock Entra :8081)."""

import os

import pytest
from playwright.sync_api import Page, expect

WEB = os.environ.get("ITP_WEB_URL", "http://localhost:5173")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: browser tests (run via make e2e)")


def start_login(page: Page, persona: str) -> None:
    """Real OIDC code+PKCE round trip through the mock Entra login page."""
    page.goto(f"{WEB}/login")
    page.get_by_role("link", name="Sign in").click()
    page.locator(f'button[data-persona="{persona}"]').click()
    page.wait_for_url(f"{WEB}/**")


def login(page: Page, persona: str) -> None:
    start_login(page, persona)
    expect(page.get_by_role("link", name="Internal Tools")).to_be_visible()


@pytest.fixture
def as_persona(page: Page):
    def _go(persona: str) -> Page:
        login(page, persona)
        return page

    return _go
