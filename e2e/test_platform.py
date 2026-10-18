import re

import pytest
from playwright.sync_api import expect

from conftest import WEB, start_login

pytestmark = pytest.mark.e2e

TOOL_LINKS = ["Review queue", "Refund requests", "Feature flags", "Complaints", "AP invoices"]


@pytest.mark.parametrize(
    ("persona", "link", "heading"),
    [
        ("ana.analyst", "Review queue", "KYC review queue"),
        ("alex.agent", "Refund requests", "Refund requests"),
        ("erin.engineer", "Feature flags", "Feature flags"),
        ("hana.handler", "Complaints", "Complaints"),
        ("cleo.clerk", "AP invoices", "AP invoices"),
    ],
)
def test_each_persona_reaches_only_its_tool(as_persona, persona, link, heading):
    page = as_persona(persona)
    nav = page.locator("nav, aside").first
    nav.get_by_role("link", name=link, exact=True).click()
    expect(page.get_by_role("heading", level=1, name=heading)).to_be_visible()
    for other in TOOL_LINKS:
        if other != link:
            expect(nav.get_by_role("link", name=other, exact=True)).to_have_count(0)


def test_server_enforces_permissions_not_just_the_nav(as_persona):
    page = as_persona("cleo.clerk")
    assert page.request.get(f"{WEB}/api/kyc/cases").status == 403
    assert page.request.get(f"{WEB}/api/ap/invoices").status == 200


def test_kyc_pii_is_masked_in_list(as_persona):
    page = as_persona("ana.analyst")
    body = page.request.get(f"{WEB}/api/kyc/cases").text()
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", body), "unmasked SSN-shaped value in KYC list"


def test_groups_overage_user_without_app_roles_is_refused_at_login(page):
    start_login(page, "olly.overage")
    expect(page.get_by_test_id("login-error")).to_contain_text("groups overage")
    assert page.request.get(f"{WEB}/api/me").status == 401


def test_auditor_reads_audit_log_but_cannot_approve(as_persona):
    page = as_persona("aud.auditor")
    page.goto(f"{WEB}/admin/audit")
    expect(page.get_by_role("heading", level=1, name="Audit log")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("^Approve"))).to_have_count(0)


def test_logged_out_user_is_sent_to_login(page):
    page.goto(f"{WEB}/kyc")
    page.wait_for_url(re.compile(r"/login"))
    expect(page.get_by_role("link", name="Sign in")).to_be_visible()
