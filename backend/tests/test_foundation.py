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
    cora = principal("cora.compliance")
    pia = principal("pia.platform")
    with session_scope() as db:
        key = next(iter(policy.list_all(db)))["key"] if policy.list_all(db) else None
    if key is None:
        pytest.skip("no policies registered")
    with session_scope() as db:
        old = policy.get(db, key)
        req = policy.request_change(db, cora, key, 12345 if isinstance(old, int) else 0.5, "tighten")
        rid = req.id
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, cora, rid, "approve", "self")
    with session_scope() as db:
        approvals.decide(db, pia, rid, "approve", "looks ok")
    with session_scope() as db:
        assert policy.get(db, key) == (12345 if isinstance(old, int) else 0.5)
        assert policy.current_version(db, key) == 2


def test_policy_value_validation():
    with session_scope() as db:
        items = policy.list_all(db)
    ints = [i for i in items if i["kind"] in ("int", "cents")]
    if not ints:
        pytest.skip("no int policies")
    with session_scope() as db, pytest.raises(Invalid):
        policy.request_change(db, principal("cora.compliance"), ints[0]["key"], -5, "bad")


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
        approvals.decide(db, pia, rid, "reject", "not now")
    with session_scope() as db, pytest.raises(Conflict):
        approvals.decide(db, principal("cam.controller"), rid, "approve", "late")
