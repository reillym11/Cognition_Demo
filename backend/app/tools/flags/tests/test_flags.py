import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from app.foundation import approvals, jobs
from app.foundation.db import session_scope, utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid
from app.foundation.models import Job
from app.tools.flags import service
from app.tools.flags.models import FlagChange, FlagEnv
from testing import principal

ON = {"enabled": True, "rollout_pct": 100, "rules": [], "default_value": False}


def make_flag(key: str = "checkout.new-flow") -> str:
    with session_scope() as db:
        service.create_flag(db, principal("erin.engineer"), key, "test", "Erin", "new feature")
    return key


def ev(key: str, env: str = "dev", default: bool = False, **ctx: str) -> dict:
    with session_scope() as db:
        return service.evaluate(db, key, env, ctx, default)


def test_new_flag_disabled_everywhere_and_missing_uses_explicit_default():
    k = make_flag()
    assert ev(k, "prod", user_id="u1")["reason"] == "DISABLED"
    assert ev("does.not-exist", default=True) == {"value": True, "reason": "FLAG_NOT_FOUND"}
    assert ev("does.not-exist", default=False)["value"] is False


def test_dev_change_applies_and_is_recorded_with_diff():
    k = make_flag()
    with session_scope() as db:
        assert service.change(db, principal("erin.engineer"), k, "dev", ON, "try it")["status"] == "applied"
    assert ev(k, user_id="u1") == {"value": True, "reason": "FULL_ROLLOUT", "version": 2}
    with session_scope() as db:
        c = db.execute(select(FlagChange)).scalar_one()
        assert c.before["enabled"] is False and c.after["enabled"] is True and c.reason == "try it"


def test_prod_change_needs_second_person():
    k = make_flag()
    with session_scope() as db:
        res = service.change(db, principal("erin.engineer"), k, "prod", ON, "launch")
    assert res["status"] == "pending_approval"
    assert ev(k, "prod", user_id="u1")["reason"] == "DISABLED"
    with session_scope() as db, pytest.raises(Conflict):
        service.change(db, principal("pat.pm"), k, "prod", {**ON, "rollout_pct": 50}, "competing")
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(
            db, principal("erin.engineer"), res["approval_request_id"], "approve", "self approve"
        )
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, principal("pat.pm"), res["approval_request_id"], "approve", "no permission")
    with session_scope() as db:
        approvals.decide(
            db, principal("pia.platform"), res["approval_request_id"], "approve", "reviewed rollout plan"
        )
    assert ev(k, "prod", user_id="u1")["value"] is True
    with session_scope() as db:
        c = db.execute(select(FlagChange).where(FlagChange.env == "prod")).scalar_one()
        assert c.actor_name == "Erin Engineer" and c.approved_by == "Pia Platform"


def test_targeting_rules():
    k = make_flag()
    with session_scope() as db:
        service.change(
            db,
            principal("erin.engineer"),
            k,
            "dev",
            {**ON, "rules": [{"attribute": "region", "op": "in", "values": ["US"]}]},
            "US only",
        )
    assert ev(k, user_id="u1", region="US")["value"] is True
    assert ev(k, user_id="u1", region="EU")["reason"] == "RULE_MISS"
    assert ev(k, user_id="u1")["reason"] == "RULE_MISS"


def test_validation():
    k = make_flag()
    for bad in (
        {**ON, "rollout_pct": 101},
        {**ON, "rollout_pct": 5.5},
        {**ON, "rules": [{"attribute": "ssn", "op": "in", "values": ["x"]}]},
        {**ON, "rules": [{"attribute": "region", "op": "regex", "values": ["x"]}]},
    ):
        with session_scope() as db, pytest.raises(Invalid):
            service.change(db, principal("erin.engineer"), k, "dev", bad, "bad config")
    with session_scope() as db, pytest.raises(Invalid):
        service.create_flag(db, principal("erin.engineer"), "Bad Key!", "", "", "reason here")


def test_stale_detection_and_report():
    k = make_flag()
    with session_scope() as db:
        e = db.execute(select(FlagEnv).where(FlagEnv.env == "prod")).scalar_one()
        e.enabled, e.rollout_pct = True, 100
        from datetime import timedelta

        e.full_rollout_since = utcnow() - timedelta(days=20)
    with session_scope() as db:
        assert [s["key"] for s in service.stale_flags(db)] == [k]
        service.stale_report(db, {})
        j = db.execute(select(Job).where(Job.kind == "core.notify_teams")).scalar_one()
        assert j.payload["channel"] == "flag-hygiene"
    jobs


def test_bucketing_deterministic_and_roughly_uniform():
    inside = sum(service.bucket("f.x", f"user-{i}") < 2500 for i in range(20_000))
    assert 4_500 < inside < 5_500
    assert service.bucket("f.x", "u") == service.bucket("f.x", "u")


@settings(max_examples=200, deadline=None)
@given(st.text(min_size=1, max_size=20), st.integers(0, 100), st.integers(0, 100))
def test_property_rollout_monotonic(uid, a, b):
    lo, hi = sorted((a, b))
    b_ = service.bucket("flag.k", uid)
    assert (b_ < lo * 100) <= (b_ < hi * 100)  # raising the % never turns a user off


def test_api_permissions(login):
    k = make_flag()
    assert (
        login("aud.auditor").put(f"/api/flags/{k}/envs/dev", json={**ON, "reason": "nope"}).status_code == 403
    )
    r = login("pat.pm").put(f"/api/flags/{k}/envs/prod", json={**ON, "reason": "launch it"})
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    r = login("erin.engineer").get(
        "/api/flags/evaluate", params={"key": k, "env": "dev", "default": True, "user_id": "u"}
    )
    assert r.json()["reason"] == "DISABLED"
