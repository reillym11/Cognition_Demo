import threading

import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy import text

from app.foundation import approvals, audit, policy
from app.foundation.authz import check_routes, require
from app.foundation.db import session_scope
from app.foundation.errors import Conflict, Forbidden, Invalid
from app.foundation.money import Money
from testing import principal


def test_host_has_no_unprotected_routes(app):
    from app.foundation.registry import get_registry

    assert check_routes(app, set(get_registry().permissions)) == []
    from app.foundation.authz import route_permissions

    assert len(route_permissions(app)) > 50, "route discovery must see included tool routers"


def test_unprotected_route_is_detected():
    a = FastAPI()
    r = APIRouter()

    @r.get("/oops")
    def oops() -> dict:
        return {}

    @r.get("/typo")
    def typo(p=__import__("fastapi").Depends(require("core.audit.raed"))) -> dict:
        return {}

    a.include_router(r)
    problems = check_routes(a, {"core.audit.read"})
    assert any("/oops" in x and "no permission" in x for x in problems)
    assert any("/typo" in x and "unknown permission" in x for x in problems)


def test_route_check_fails_closed_when_no_routes_found():
    assert check_routes(FastAPI(), set()) != []


def test_health_public_me_requires_login(app):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/me").status_code == 401
    r = c.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_me_lists_permissions_and_nav(login):
    r = login("aud.auditor").get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert "core.audit.read" in body["permissions"]
    assert any(n["path"] == "/admin/audit" for n in body["nav"])


def test_csrf_required_on_mutations(login):
    c = login("aud.auditor")
    c.headers.pop("X-CSRF-Token")
    assert c.post("/api/auth/logout").status_code == 403


def test_logout_ends_session(login):
    c = login("aud.auditor")
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/me").status_code == 401


def test_role_revocation_takes_effect_mid_session(login, directory, monkeypatch):
    from app.foundation.settings import get_settings

    monkeypatch.setattr(get_settings(), "roles_revalidate_seconds", 0)
    c = login("aud.auditor")
    assert c.get("/api/audit/events").status_code == 200
    oid = "00000000-0000-4000-8000-000000000011"
    directory.entries[oid] = directory.entries[oid].__class__(oid, True, [])
    assert c.get("/api/audit/events").status_code == 403
    directory.entries[oid] = directory.entries[oid].__class__(oid, False, [])
    assert c.get("/api/me").status_code == 401


def test_directory_cannot_add_roles_the_token_did_not_carry(login, directory, monkeypatch):
    from app.foundation.settings import get_settings

    monkeypatch.setattr(get_settings(), "roles_revalidate_seconds", 0)
    c = login("aud.auditor")
    oid = "00000000-0000-4000-8000-000000000011"
    before = directory.entries[oid]
    directory.entries[oid] = before.__class__(oid, True, [*before.roles, "Platform.Admin"])
    me = c.get("/api/me").json()
    assert me["roles"] == sorted(before.roles)
    assert "Platform.Admin" not in me["roles"]


def test_mock_directory_and_admin_require_api_key():
    from fastapi.testclient import TestClient

    from app.foundation.settings import get_settings
    from mocks import app as mocks

    m = TestClient(mocks.app)
    oid = "00000000-0000-4000-8000-000000000011"
    good = {"Authorization": f"Bearer {get_settings().directory_api_key}"}
    bad = {"Authorization": "Bearer wrong"}
    for h in ({}, bad):
        assert m.get(f"/directory/users/{oid}", headers=h).status_code == 401
        assert (
            m.patch(f"/directory/users/{oid}", json={"appRoles": ["Platform.Admin"]}, headers=h).status_code
            == 401
        )
        assert m.post("/admin/reset", headers=h).status_code == 401
        assert m.post("/admin/faults", json={"name": "x", "mode": "timeout"}, headers=h).status_code == 401
    assert "Platform.Admin" not in m.get(f"/directory/users/{oid}", headers=good).json()["appRoles"]


def test_http_directory_sends_api_key(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient

    from app.foundation.adapters.directory import HttpDirectory
    from app.foundation.settings import get_settings
    from mocks import app as mocks

    m = TestClient(mocks.app)
    monkeypatch.setattr(httpx, "get", lambda url, **kw: m.get(url, **kw))
    oid = "00000000-0000-4000-8000-000000000011"
    entry = HttpDirectory("http://testserver", get_settings().directory_api_key).lookup(oid)
    assert entry is not None and entry.enabled
    with pytest.raises(httpx.HTTPStatusError):
        HttpDirectory("http://testserver", "wrong").lookup(oid)


def test_idle_timeout(login, monkeypatch):
    from app.foundation.settings import get_settings

    c = login("aud.auditor")
    monkeypatch.setattr(get_settings(), "session_idle_minutes", -1)
    assert c.get("/api/me").status_code == 401


def test_groups_overage_is_denied_with_clear_error():
    from app.foundation.auth import roles_from_claims

    with pytest.raises(PermissionError, match="groups_overage"):
        roles_from_claims({"_claim_names": {"groups": "src1"}})
    with pytest.raises(PermissionError, match="no_roles"):
        roles_from_claims({})
    assert roles_from_claims({"roles": ["b", "a"]}) == ["a", "b"]


def test_audit_chain_verifies_and_detects_tampering():
    from testing import SUPER

    p = principal("aud.auditor")
    with session_scope() as db:
        for i in range(5):
            audit.record(
                db, p, "test.event", "policy", i, chain="t", reason=f"r{i}", before={"a": 1}, after={"a": i}
            )
    with session_scope() as db:
        assert audit.verify_chain(db, "t").ok
    with session_scope() as db, pytest.raises(Exception, match=r"append-only|permission denied"):
        db.execute(text("UPDATE audit_events SET reason='x' WHERE seq=2"))
    with SUPER.begin() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(text("UPDATE audit_events SET reason='x' WHERE seq=3"))
    with session_scope() as db:
        r = audit.verify_chain(db, "t")
    assert not r.ok and r.first_bad_seq == 3


def test_audit_chain_concurrent_writers():
    p = principal("aud.auditor")

    def w(i: int) -> None:
        for j in range(5):
            with session_scope() as db:
                audit.record(db, p, "test.concurrent", "policy", f"{i}-{j}", chain="conc")

    ts = [threading.Thread(target=w, args=(i,)) for i in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    with session_scope() as db:
        r = audit.verify_chain(db, "conc")
    assert r.ok and r.count == 100


def test_audit_diff_keeps_changed_fields_only():
    b, a = audit.diff({"x": 1, "y": 2}, {"x": 1, "y": 3})
    assert b == {"y": 2} and a == {"y": 3}


def test_policy_change_requires_someone_else(login):
    pia = principal("pia.platform")
    key = "refunds.approval_threshold_cents"
    with session_scope() as db:
        rid = policy.request_change(db, pia, key, 12345, "tighten").id
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, pia, rid, "approve", "self")
    with session_scope() as db, pytest.raises(Forbidden, match=r"refunds\.policy\.approve"):
        approvals.decide(db, principal("cora.compliance"), rid, "approve", "not my domain")
    with session_scope() as db:
        approvals.decide(db, principal("cam.controller"), rid, "approve", "looks ok")
    with session_scope() as db:
        assert policy.get(db, key) == 12345
        assert policy.current_version(db, key) == 2


def test_kyc_policy_needs_kyc_policy_approver():
    cam = principal("cam.controller")
    key = "kyc.fastlane_criteria"
    tighter = {"max_vendor_score": 10, "max_watchlist_hits": 0, "require_docs_verified": True}
    with session_scope() as db:
        rid = policy.request_change(db, cam, key, tighter, "tighten").id
    with session_scope() as db, pytest.raises(Forbidden, match=r"kyc\.policy\.approve"):
        approvals.decide(db, principal("pia.platform"), rid, "approve", "not my domain")
    with session_scope() as db:
        approvals.decide(db, principal("cora.compliance"), rid, "approve", "looks ok")
    with session_scope() as db:
        assert policy.get(db, key) == tighter


def test_policy_value_validation():
    with session_scope() as db, pytest.raises(Invalid):
        policy.request_change(db, principal("cora.compliance"), "ap.po_tolerance_bps", -5, "bad")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        (
            "kyc.fastlane_criteria",
            {"max_vendor_score": 1_000_000, "max_watchlist_hits": 0, "require_docs_verified": True},
        ),
        (
            "kyc.fastlane_criteria",
            {"max_vendor_score": 20, "max_watchlist_hits": 5, "require_docs_verified": True},
        ),
        (
            "kyc.fastlane_criteria",
            {"max_vendor_score": 20, "max_watchlist_hits": 0, "require_docs_verified": False},
        ),
        ("kyc.fastlane_criteria", {"max_vendor_score": 20, "max_watchlist_hits": 0}),
        (
            "kyc.fastlane_criteria",
            {"max_vendor_score": "20", "max_watchlist_hits": 0, "require_docs_verified": True},
        ),
        ("kyc.fastlane_criteria", [20, 0, True]),
        ("kyc.fastlane_criteria", None),
        ("kyc.sla_hours", {"low": 72, "medium": 48}),
        ("kyc.sla_hours", {"low": 72, "medium": 48, "high": 0}),
        ("kyc.sla_hours", {"low": 24, "medium": 48, "high": 72}),
        ("kyc.sla_hours", {"low": 72, "medium": 48, "high": 24, "extra": 1}),
        ("refunds.velocity", {"window_minutes": 0, "max_requests": 10}),
        ("refunds.velocity", {"window_minutes": 60, "max_requests": 1_000_000}),
        ("refunds.velocity", {"window_minutes": 60, "max_requests": True}),
        ("refunds.velocity", "off"),
        ("ap.confidence_threshold", True),
    ],
)
def test_json_policy_schema_rejects_weakened_or_malformed(key, value):
    with pytest.raises(Invalid):
        policy.validate(key, value)
    with session_scope() as db, pytest.raises(Invalid):
        policy.request_change(db, principal("pia.platform"), key, value, "weaken")


def test_malformed_stored_policy_falls_back_to_default(caplog):
    from app.foundation.models import PolicyValue
    from app.foundation.registry import get_registry

    key = "refunds.velocity"
    with session_scope() as db:
        db.add(PolicyValue(key=key, version=policy.current_version(db, key) + 1, value=[], created_by="test"))
    with session_scope() as db:
        assert policy.get(db, key) == get_registry().policies[key].default
    assert any("refunds.velocity" in r.getMessage() for r in caplog.records)


def _raw_policy_request(db, key, value, stage_perm):
    return approvals.create_request(
        db,
        principal("pia.platform"),
        kind="core.policy_change",
        subject_type="policy",
        subject_id=key,
        title="legacy request",
        reason="created before schemas",
        chain="core",
        requirement=approvals.Requirement(stages=[approvals.Stage("Policy approver", stage_perm)]),
        payload={"key": key, "old": None, "new": value, "base_version": policy.current_version(db, key)},
    ).id


def test_apply_revalidates_value_and_approver():
    key = "refunds.velocity"
    with session_scope() as db:
        rid = _raw_policy_request(
            db, key, {"window_minutes": 0, "max_requests": 10}, "refunds.policy.approve"
        )
    with pytest.raises(Invalid), session_scope() as db:
        approvals.decide(db, principal("cam.controller"), rid, "approve", "looks ok")
    with session_scope() as db:
        approvals.decide(db, principal("cam.controller"), rid, "reject", "invalid")
        rid = _raw_policy_request(db, key, {"window_minutes": 30, "max_requests": 5}, "kyc.policy.approve")
    with pytest.raises(Conflict, match=r"refunds\.policy\.approve"), session_scope() as db:
        approvals.decide(db, principal("cora.compliance"), rid, "approve", "looks ok")
    with session_scope() as db:
        assert policy.current_version(db, key) == 1


def _manifest(**pdef):
    from app.foundation.registry import PolicyDef, ToolManifest

    return ToolManifest(
        key="t",
        name="t",
        description="t",
        permissions={"t.policy.approve": "approve", "t.other": "other"},
        grants={"R": ["t.policy.approve"]},
        policies={"t.p": PolicyDef(**{"default": {"a": 1}, "description": "d", "kind": "json", **pdef})},
    )


@pytest.mark.parametrize(
    "pdef",
    [
        {"approver": "t.policy.approve", "schema": None},
        {"approver": ""},
        {"approver": "t.policy.approve", "default": {"a": "not an int"}},
        {"approver": "core.policy.approve"},
        {"approver": "t.other"},
        {"approver": "t.nope"},
    ],
)
def test_registry_rejects_unsafe_policy_defs(pdef):
    from pydantic import BaseModel

    from app.foundation.registry import Registry

    class S(BaseModel):
        a: int

    pdef = {"schema": S, **pdef}
    with pytest.raises(RuntimeError):
        Registry([_manifest(**pdef)])


def test_registry_accepts_schema_and_owned_approver():
    from pydantic import BaseModel

    from app.foundation.registry import Registry

    class S(BaseModel):
        a: int

    Registry([_manifest(schema=S, approver="t.policy.approve")])


def test_money_rejects_floats_and_other_currencies():
    with pytest.raises(TypeError):
        Money(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Money(100, "EUR")
    assert (Money(150) + Money(50)).format() == "$2.00"


def test_closed_request_rejects_decisions():
    cora = principal("cora.compliance")
    pia = principal("pia.platform")
    with session_scope() as db:
        items = policy.list_all(db)
    if not items:
        pytest.skip("no policies")
    key = items[0]["key"]
    with session_scope() as db:
        rid = policy.request_change(
            db, cora, key, policy.validate(key, 1 if items[0]["kind"] != "float" else 0.1), "x y z"
        ).id
    with session_scope() as db:
        approvals.decide(db, principal("cam.controller"), rid, "reject", "not now")
    with session_scope() as db, pytest.raises(Conflict):
        approvals.decide(db, principal("cam.controller"), rid, "approve", "late")


def test_redact_text_masks_pii_shapes():
    from app.foundation.datacls import redact_text

    out = redact_text("mail jane.doe+x@mail.example.com ssn 123-45-6789 acct 123456789012")
    assert out == "mail [REDACTED-EMAIL] ssn [REDACTED-SSN] acct [REDACTED-NUMBER]"


def test_redact_text_is_linear_on_adversarial_input():
    import time

    from app.foundation.datacls import REDACT_MAX_CHARS, redact_text

    # The old unbounded email pattern took ~6 s here (quadratic backtracking).
    payload = "a." * (REDACT_MAX_CHARS // 2)
    start = time.perf_counter()
    redact_text(payload)
    redact_text("/" + payload + "@x")
    assert time.perf_counter() - start < 0.1


def test_redact_text_bounds_input_length():
    from app.foundation.datacls import REDACT_MAX_CHARS, redact_text

    out = redact_text("x" * (REDACT_MAX_CHARS * 4) + " jane@example.com")
    assert len(out) <= REDACT_MAX_CHARS + 20
    assert "jane@example.com" not in out


def _evidence_events(n: int) -> None:
    p = principal("aud.auditor")
    with session_scope() as db:
        for i in range(n):
            audit.record(db, p, "test.event", "policy", i, chain="t", reason=f"r{i}")


def _set_policy(key: str, value: int) -> None:
    from app.foundation.models import PolicyValue

    with session_scope() as db:
        v = policy.current_version(db, key) + 1
        db.add(PolicyValue(key=key, version=v, value=value, created_by="test"))


def test_evidence_pack_streams_events_and_is_audited(login):
    import io
    import json
    import zipfile
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.foundation.models import AuditEvent

    _evidence_events(3)
    today = datetime.now(UTC).date()
    r = login("aud.auditor").get(
        "/api/audit/evidence-pack", params={"start": today, "end": today, "reason": "quarterly audit"}
    )
    assert r.status_code == 200, r.text
    assert int(r.headers["content-length"]) == len(r.content)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    lines = z.read("audit-events.jsonl").decode().splitlines()
    assert [json.loads(x)["action"] for x in lines] == ["test.event"] * 3
    assert all(v["ok"] for v in json.loads(z.read("chain-verification.json")))
    with session_scope() as db:
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "audit.evidence_pack")).scalar_one()
    assert ev.after["events"] == 3 and ev.reason == "quarterly audit"


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [
        ("0001-01-01", "9998-12-31", "evidence_range_too_long"),
        ("2026-01-01", "2027-01-02", "evidence_range_too_long"),  # 367 days inclusive
        ("2026-02-01", "2026-01-31", "evidence_range_invalid"),
    ],
)
def test_evidence_pack_rejects_bad_ranges(login, start, end, code):
    r = login("aud.auditor").get(
        "/api/audit/evidence-pack", params={"start": start, "end": end, "reason": "quarterly audit"}
    )
    assert r.status_code == 422 and r.json()["code"] == code


def test_evidence_pack_range_boundary_is_inclusive(login):
    c = login("aud.auditor")
    params = {"start": "2026-01-01", "end": "2027-01-01", "reason": "annual"}  # 366 days inclusive
    assert c.get("/api/audit/evidence-pack", params=params).status_code == 200
    _set_policy("core.evidence_pack_max_days", 365)
    r = c.get("/api/audit/evidence-pack", params=params)
    assert r.status_code == 422 and r.json()["code"] == "evidence_range_too_long"


def test_evidence_pack_rejects_too_many_events(login):
    from datetime import UTC, datetime

    _evidence_events(3)
    today = datetime.now(UTC).date()
    params = {"start": today, "end": today, "reason": "quarterly audit"}
    _set_policy("core.evidence_pack_max_events", 3)
    assert login("aud.auditor").get("/api/audit/evidence-pack", params=params).status_code == 200
    _set_policy("core.evidence_pack_max_events", 2)
    r = login("aud.auditor").get("/api/audit/evidence-pack", params=params)
    assert r.status_code == 422 and r.json()["code"] == "evidence_too_many_events"


def test_rate_limit_key_ignores_forged_session_cookies(login):
    from starlette.requests import Request

    from app.foundation import auth
    from app.foundation.ratelimit import client_key

    def req(cookie: str | None) -> Request:
        headers = [(b"cookie", f"{auth.SESSION_COOKIE}={cookie}".encode())] if cookie else []
        return Request({"type": "http", "headers": headers, "client": ("10.0.0.7", 1234), "state": {}})

    assert client_key(req(None)) == "ip:10.0.0.7"
    assert client_key(req("forged-aaaaaaaaaaaaaaa")) == "ip:10.0.0.7"
    assert client_key(req("forged-bbbbbbbbbbbbbbb")) == "ip:10.0.0.7"
    token = login("ana.analyst").cookies.get(auth.SESSION_COOKIE)
    assert client_key(req(token)) == f"session:{auth._hash(token)}"


def test_sensitive_routes_carry_sensitive_rate_limit(app):
    from app.foundation.authz import _api_routes
    from app.foundation.ratelimit import _sensitive

    sensitive = [
        r
        for r in _api_routes(app.routes)
        if (
            r.path.endswith(("/reveal", "/export", ".csv"))
            or r.path in {"/api/auth/login", "/api/auth/callback"}
        )
    ]
    assert len(sensitive) >= 9
    missing = [r.path for r in sensitive if _sensitive not in {d.call for d in r.dependant.dependencies}]
    assert missing == []


def test_sensitive_rate_limit_returns_429(login, monkeypatch):
    from app.foundation.settings import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_sensitive", "2/minute")
    c = login("ana.analyst")
    codes = [
        c.post("/api/kyc/cases/999999/reveal", json={"field": "email", "reason": "check"}).status_code
        for _ in range(3)
    ]
    assert 429 not in codes[:2] and codes[2] == 429
    assert (
        c.post("/api/kyc/cases/999999/reveal", json={"field": "email", "reason": "check"}).json()["code"]
        == "rate_limited"
    )
        approvals.decide(db, pia, rid, "approve", "late")
