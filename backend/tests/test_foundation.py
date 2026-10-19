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
        approvals.decide(db, pia, rid, "approve", "late")
