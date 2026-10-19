import threading

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select, text

from app.foundation import approvals, audit, policy
from app.foundation.db import session_scope
from app.foundation.errors import Conflict, Forbidden, Invalid
from app.tools.kyc import service
from app.tools.kyc.models import KycCase, KycDecision
from app.tools.kyc.seed import seed
from testing import principal


def make_case(**kw) -> int:
    from datetime import timedelta

    from app.foundation.db import utcnow

    with session_scope() as db:
        n = db.execute(select(func.count()).select_from(KycCase)).scalar_one()
        c = KycCase(
            ref=f"KYC-T{n:05d}",
            applicant_name="Jane Q Test",
            email="jane@example.com",
            dob="1990-01-01",
            ssn="900-12-3456",
            address="1 Test St, Springfield",
            country="US",
            region=kw.pop("region", "US"),
            risk_level=kw.pop("risk_level", "medium"),
            vendor_score=kw.pop("vendor_score", 50),
            watchlist_hits=kw.pop("watchlist_hits", 0),
            docs_verified=kw.pop("docs_verified", True),
            status="new",
            touched_by=[],
            sla_due_at=utcnow() + timedelta(hours=48),
            **kw,
        )
        db.add(c)
        db.flush()
        return c.id


def recommend_flow(case_id: int, preparer: str = "ana.analyst") -> int:
    with session_scope() as db:
        service.claim(db, principal(preparer), case_id)
    with session_scope() as db:
        service.recommend(db, principal(preparer), case_id, "approve", "DOCS_VERIFIED", "docs match")
    with session_scope() as db:
        return approvals.open_for_subject(db, service.RES, case_id).id


def test_four_eyes_preparer_cannot_decide():
    cid = make_case()
    rid = recommend_flow(cid)
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, principal("ana.analyst"), rid, "approve", "self")
    with session_scope() as db:
        approvals.decide(db, principal("avery.analyst"), rid, "approve", "agree")
    with session_scope() as db:
        c = db.get(KycCase, cid)
        assert c.status == "approved" and c.decided_by.endswith("002")
        d = db.execute(select(KycDecision).where(KycDecision.case_id == cid)).scalar_one()
        assert d.reason_code == "DOCS_VERIFIED" and d.recommended_by.endswith("001")


def test_reassignment_loophole_closed():
    """Avery touches the case, releases it, Ana prepares it: Avery still can't decide."""
    cid = make_case()
    with session_scope() as db:
        service.claim(db, principal("avery.analyst"), cid)
    with session_scope() as db:
        service.release(db, principal("avery.analyst"), cid, "wrong queue")
    rid = recommend_flow(cid)
    with session_scope() as db, pytest.raises(Forbidden, match="excluded"):
        approvals.decide(db, principal("avery.analyst"), rid, "approve", "looks ok")
    with session_scope() as db:
        approvals.decide(db, principal("sam.senior"), rid, "approve", "looks ok")


def test_high_risk_needs_senior():
    cid = make_case(risk_level="high")
    with session_scope() as db, pytest.raises(Forbidden):
        service.claim(db, principal("ana.analyst"), cid)
    rid = recommend_flow(cid, preparer="sam.senior")
    with session_scope() as db, pytest.raises(Forbidden, match=r"kyc\.decide_high"):
        approvals.decide(db, principal("avery.analyst"), rid, "approve", "looks ok")


def test_escalation_routes_to_seniors():
    cid = make_case()
    with session_scope() as db:
        service.claim(db, principal("ana.analyst"), cid)
    with session_scope() as db:
        service.escalate(db, principal("ana.analyst"), cid, "odd documents")
    with session_scope() as db, pytest.raises(Forbidden):
        service.claim(db, principal("avery.analyst"), cid)


def test_returned_recommendation_goes_back_to_preparer():
    cid = make_case()
    rid = recommend_flow(cid)
    with session_scope() as db:
        approvals.decide(db, principal("avery.analyst"), rid, "reject", "need proof of address")
    with session_scope() as db:
        c = db.get(KycCase, cid)
        assert c.status == "in_review" and c.assigned_to.endswith("001") and c.decision is None


def test_reason_codes_and_reasons_required():
    cid = make_case()
    with session_scope() as db:
        service.claim(db, principal("ana.analyst"), cid)
    with session_scope() as db, pytest.raises(Invalid):
        service.recommend(db, principal("ana.analyst"), cid, "approve", "WATCHLIST_MATCH", "x y")
    with session_scope() as db, pytest.raises(Invalid):
        service.recommend(db, principal("ana.analyst"), cid, "approve", "DOCS_VERIFIED", "  ")


def test_claim_race_one_winner():
    cid = make_case()
    results: list[str] = []

    def go(u: str) -> None:
        try:
            with session_scope() as db:
                service.claim(db, principal(u), cid)
            results.append("ok")
        except Conflict:
            results.append("conflict")

    ts = [threading.Thread(target=go, args=(u,)) for u in ["ana.analyst", "avery.analyst", "sam.senior"] * 3]
    [t.start() for t in ts]
    [t.join() for t in ts]
    # The same user re-claiming their own case is idempotent, so winners == attempts by the first claimant.
    with session_scope() as db:
        owner = db.get(KycCase, cid).assigned_to
    assert results.count("ok") == 1 and owner is not None


def test_fastlane_clears_only_eligible_and_samples_qa():
    ok = [make_case(risk_level="low", vendor_score=10) for _ in range(5)]
    hit = make_case(risk_level="low", vendor_score=10, watchlist_hits=1)
    docs = make_case(risk_level="low", vendor_score=10, docs_verified=False)
    med = make_case(risk_level="medium", vendor_score=10)
    with session_scope() as db:
        policy_rate = policy.get(db, "kyc.qa_sample_rate")
        assert policy_rate == 0.02
    with session_scope() as db:
        db.execute(text("UPDATE policy_values SET value = '1.0' WHERE key='kyc.qa_sample_rate'"))
    with session_scope() as db:
        service.run_fastlane(db, {"seed": 1})
    with session_scope() as db:
        for cid in ok:
            c = db.get(KycCase, cid)
            assert (
                c.status == "auto_cleared"
                and c.decided_by == "system:kyc-fastlane"
                and c.decision_code == "AUTO_CLEAR"
            )
            assert c.qa_status == "pending"
        for cid in (hit, docs, med):
            assert db.get(KycCase, cid).status == "new"
        assert audit.verify_chain(db, "kyc").ok
        n = db.execute(
            text(
                "SELECT count(*) FROM audit_events WHERE actor_id='system:kyc-fastlane' AND reason='AUTO_CLEAR'"
            )
        ).scalar_one()
        assert n == 5


def test_qa_failure_reopens_for_senior():
    cid = make_case(risk_level="low", vendor_score=5)
    with session_scope() as db:
        db.execute(text("UPDATE policy_values SET value = '1.0' WHERE key='kyc.qa_sample_rate'"))
    with session_scope() as db:
        service.run_fastlane(db, {})
    with session_scope() as db:
        service.qa_review(db, principal("sam.senior"), cid, "failed", "address mismatch")
    with session_scope() as db:
        c = db.get(KycCase, cid)
        assert c.status == "new" and c.requires_senior


def test_decision_records_are_append_only():
    cid = make_case()
    rid = recommend_flow(cid)
    with session_scope() as db:
        approvals.decide(db, principal("avery.analyst"), rid, "approve", "looks ok")
    with session_scope() as db, pytest.raises(Exception, match=r"append-only|permission denied"):
        db.execute(text("UPDATE kyc_decisions SET decision='reject'"))


def test_region_row_scope_and_masking(login):
    us = make_case(region="US")
    eu = make_case(region="EU")
    c = login("ana.analyst")
    body = c.get("/api/kyc/cases?status=open").json()
    ids = {i["id"] for i in body["items"]}
    assert us in ids and eu not in ids
    assert c.get(f"/api/kyc/cases/{eu}").status_code == 404
    item = next(i for i in body["items"] if i["id"] == us)
    assert item["ssn"] == "***-**-3456" and item["email"].startswith("j***@")
    assert login("cora.compliance").get(f"/api/kyc/cases/{eu}").status_code == 200


def test_out_of_region_approver_cannot_see_or_decide(login):
    from dataclasses import replace

    eu = make_case(region="EU")
    eu_preparer = replace(principal("avery.analyst"), region="EU")
    with session_scope() as db:
        service.claim(db, eu_preparer, eu)
    with session_scope() as db:
        service.recommend(db, eu_preparer, eu, "approve", "DOCS_VERIFIED", "docs match")
    with session_scope() as db:
        rid = approvals.open_for_subject(db, service.RES, eu).id

    us = login("ana.analyst")
    assert rid not in {r["id"] for r in us.get("/api/approvals/inbox").json()}
    assert us.get(f"/api/approvals/{rid}").status_code == 404
    r = us.post(f"/api/approvals/{rid}/decide", json={"decision": "approve", "reason": "looks fine"})
    assert r.status_code == 403
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, principal("ana.analyst"), rid, "approve", "looks fine")
    with session_scope() as db:
        assert db.get(KycCase, eu).status == "pending_decision"

    eu_decider = replace(principal("ana.analyst"), region="EU")
    with session_scope() as db:
        approvals.decide(db, eu_decider, rid, "approve", "agree")
    with session_scope() as db:
        assert db.get(KycCase, eu).status == "approved"


def test_reveal_is_audited_and_permissioned(login):
    cid = make_case()
    r = login("ana.analyst").post(
        f"/api/kyc/cases/{cid}/reveal", json={"field": "ssn", "reason": "verify identity"}
    )
    assert r.json()["value"] == "900-12-3456"
    assert (
        login("aud.auditor")
        .post(f"/api/kyc/cases/{cid}/reveal", json={"field": "ssn", "reason": "x y z"})
        .status_code
        == 403
    )
    assert login("ana.analyst").post(f"/api/kyc/cases/{cid}/reveal", json={"field": "ssn"}).status_code == 422
    with session_scope() as db:
        n = db.execute(text("SELECT count(*) FROM audit_events WHERE action='kyc.pii_revealed'")).scalar_one()
    assert n == 1


def test_export_masks_and_audits(login):
    make_case()
    c = login("cora.compliance")
    assert c.get("/api/kyc/export").status_code == 422
    r = c.get("/api/kyc/export?reason=quarterly+review")
    assert r.status_code == 200 and "900-12-3456" not in r.text and "J*** Q*** T***" in r.text


def test_seed_25k_and_list_fast(login):
    import time

    t = time.time()
    with session_scope() as db:
        seed(db, 1.0)
    assert time.time() - t < 30
    c = login("cora.compliance")
    t = time.time()
    r = c.get("/api/kyc/cases?status=open&sort=sla_due_at&risk=high")
    assert r.status_code == 200 and time.time() - t < 1.0
    assert c.get("/api/kyc/cases").json()["total"] == 25_000


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    preparers=st.lists(
        st.sampled_from(["ana.analyst", "avery.analyst", "sam.senior"]), min_size=1, max_size=3
    ),
    decider=st.sampled_from(["ana.analyst", "avery.analyst", "sam.senior", "cora.compliance"]),
)
def test_property_nobody_who_touched_can_decide(preparers, decider):
    cid = make_case()
    for u in preparers[:-1]:
        with session_scope() as db:
            service.claim(db, principal(u), cid)
        with session_scope() as db:
            service.release(db, principal(u), cid, "handoff")
    rid = recommend_flow(cid, preparers[-1])
    try:
        with session_scope() as db:
            approvals.decide(db, principal(decider), rid, "approve", "looks ok")
        decided = True
    except Forbidden:
        decided = False
    assert decided == (decider not in preparers and decider != "cora.compliance")
