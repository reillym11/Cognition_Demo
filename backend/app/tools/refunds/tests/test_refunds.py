import contextlib
import dataclasses
import threading

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select, update

from app.foundation import approvals, jobs
from app.foundation.db import session_scope, utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid, NotFound
from app.foundation.models import Job
from app.tools.refunds import service
from app.tools.refunds.models import RESERVING, Refund, Transaction
from app.tools.refunds.processor import HttpProcessor, set_processor
from mocks import app as mocks
from testing import principal


@pytest.fixture(autouse=True)
def processor():
    mocks.reset()
    set_processor(HttpProcessor(TestClient(mocks.app)))
    yield
    set_processor(None)


def fault(mode: str, times: int = 1) -> None:
    mocks.STATE["faults"]["processor.refund"] = {"mode": mode, "times": times}


def processor_count(charge_id: str) -> int:
    return sum(1 for r in mocks.STATE["refunds"].values() if r["charge_id"] == charge_id)


def make_txn(amount_cents: int = 100_000, region: str = "US") -> int:
    with session_scope() as db:
        n = db.execute(select(func.count()).select_from(Transaction)).scalar_one()
        t = Transaction(
            charge_id=f"ch_T{n:05d}",
            merchant="Test Market",
            region=region,
            customer_name="Pat Customer",
            customer_email="pat@example.com",
            card_last4="4242",
            amount_cents=amount_cents,
            currency="USD",
            captured_at=utcnow(),
        )
        db.add(t)
        db.flush()
        return t.id


def request(txn: int, cents: int, who: str = "support.agent") -> int:
    with session_scope() as db:
        return service.request_refund(db, principal(who), txn, cents, "GOODWILL", "customer goodwill").id


def run_jobs() -> None:
    with session_scope() as db:  # skip Teams deliveries; they go to the outbox and are asserted separately
        db.execute(update(Job).where(Job.kind == "core.notify_teams").values(status="succeeded"))
    jobs.run_until_idle(include_future=True)


def status(rid: int) -> str:
    with session_scope() as db:
        return db.get(Refund, rid).status


def test_under_threshold_executes_without_second_person():
    txn = make_txn()
    rid = request(txn, 10_000)
    assert status(rid) == "approved"
    run_jobs()
    assert status(rid) == "succeeded"
    with session_scope() as db:
        assert db.get(Refund, rid).processor_ref.startswith("re_")


def test_over_threshold_needs_different_approver():
    txn = make_txn()
    rid = request(txn, 60_000)
    assert status(rid) == "pending_approval"
    with session_scope() as db:
        req_id = db.get(Refund, rid).approval_request_id
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, principal("support.agent"), req_id, "approve", "my own")
    with session_scope() as db, pytest.raises(Forbidden):
        approvals.decide(db, principal("compliance.admin"), req_id, "approve", "not finance")
    with session_scope() as db:
        approvals.decide(db, principal("finance.approver"), req_id, "approve", "verified with customer")
    run_jobs()
    assert status(rid) == "succeeded"


def test_split_refunds_cannot_dodge_threshold():
    txn = make_txn()
    assert status(request(txn, 30_000)) == "approved"
    assert status(request(txn, 30_000)) == "pending_approval"  # cumulative 600 > 500


def test_over_refund_blocked_including_pending():
    txn = make_txn(50_000)
    request(txn, 40_000)
    with pytest.raises(Conflict, match="exceeds the refundable balance"):
        request(txn, 20_000)


def test_rejection_releases_reservation():
    txn = make_txn(80_000)
    rid = request(txn, 70_000)
    with session_scope() as db:
        req_id = db.get(Refund, rid).approval_request_id
        approvals.decide(db, principal("finance.approver"), req_id, "reject", "no evidence")
    assert status(rid) == "rejected"
    with session_scope() as db:
        assert service.reserved_cents(db, txn) == 0
    request(txn, 40_000)


def test_validation():
    txn = make_txn()
    with session_scope() as db, pytest.raises(Invalid):
        service.request_refund(db, principal("support.agent"), txn, 0, "GOODWILL", "zero")
    with session_scope() as db, pytest.raises(Invalid):
        service.request_refund(db, principal("support.agent"), txn, 100, "BECAUSE", "bad code")
    with session_scope() as db, pytest.raises(Invalid):
        service.request_refund(db, principal("support.agent"), txn, 100, "GOODWILL", "")
    with session_scope() as db, pytest.raises(Invalid):
        service.request_refund(db, principal("support.agent"), txn, 10.5, "GOODWILL", "float")


def test_contractor_always_needs_approval_and_sees_masked_pii():
    txn = make_txn(region="EU")
    assert status(request(txn, 500, who="support.contractor")) == "pending_approval"
    with session_scope() as db:
        d = service.txn_dict(service.get_txn(db, principal("support.contractor"), txn))
        assert d["customer_email"] != "pat@example.com"
    with session_scope() as db, pytest.raises(Forbidden):
        service.reveal(db, principal("support.contractor"), txn, "customer_email", "curious")


def test_velocity_flag_forces_approval():
    txn = make_txn(10_000_000)
    for _ in range(10):
        request(txn, 100)
    rid = request(txn, 100)
    with session_scope() as db:
        r = db.get(Refund, rid)
        assert r.velocity_flag and r.status == "pending_approval"


def test_lost_response_reconciles_without_double_refund():
    txn = make_txn()
    rid = request(txn, 10_000)
    fault("lost_response")
    jobs.run_until_idle()
    assert status(rid) == "unknown"
    with session_scope() as db:
        charge = service.get_txn(db, principal("support.agent"), txn).charge_id
    assert processor_count(charge) == 1  # it happened, we just didn't hear back
    with session_scope() as db:
        assert service.reserved_cents(db, txn) == 10_000  # unknown still reserves
    run_jobs()
    assert status(rid) == "succeeded"
    assert processor_count(charge) == 1


def test_5xx_before_processing_reconciles_then_resends_once():
    txn = make_txn()
    rid = request(txn, 10_000)
    fault("error_500")
    jobs.run_until_idle()
    assert status(rid) == "unknown"
    run_jobs()
    assert status(rid) == "succeeded"
    with session_scope() as db:
        charge = service.get_txn(db, principal("support.agent"), txn).charge_id
    assert processor_count(charge) == 1


def test_teams_notification_enqueued_for_approval():
    txn = make_txn()
    request(txn, 60_000)
    with session_scope() as db:
        j = db.execute(select(Job).where(Job.kind == "core.notify_teams")).scalars().all()
        assert j and j[0].payload["channel"] == "refund-approvals"
        assert "pat@example.com" not in str(j[0].payload)


def test_concurrent_requests_never_exceed_captured():
    txn = make_txn(100_000)
    results: list[str] = []

    def go() -> None:
        try:
            request(txn, 30_000)
            results.append("ok")
        except Conflict:
            results.append("conflict")

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count("ok") == 3
    with session_scope() as db:
        assert service.reserved_cents(db, txn) == 90_000


def test_concurrent_requests_on_distinct_charges_respect_velocity():
    txns = [make_txn(100_000) for _ in range(20)]
    barrier = threading.Barrier(len(txns))
    ids: list[int] = []

    def go(txn: int) -> None:
        barrier.wait()
        ids.append(request(txn, 100))

    threads = [threading.Thread(target=go, args=(t,)) for t in txns]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with session_scope() as db:
        rows = db.execute(select(Refund).where(Refund.id.in_(ids))).scalars().all()
        assert len(rows) == 20
        assert sum(1 for r in rows if r.status == "approved") == 10  # refunds.velocity max_requests
        assert sum(1 for r in rows if r.velocity_flag) == 10


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    st.lists(st.integers(min_value=1, max_value=40_000), min_size=1, max_size=12),
    st.integers(10_000, 100_000),
)
def test_property_reserved_never_exceeds_captured(amounts, captured):
    txn = make_txn(captured)
    for a in amounts:
        with contextlib.suppress(Conflict):
            request(txn, a)
    with session_scope() as db:
        total = db.execute(
            select(func.coalesce(func.sum(Refund.amount_cents), 0)).where(
                Refund.transaction_id == txn, Refund.status.in_(RESERVING)
            )
        ).scalar_one()
    assert total <= captured


def test_api_masks_and_enforces(login):
    txn = make_txn()
    agent = login("support.agent")
    r = agent.get(f"/api/refunds/transactions/{txn}")
    assert r.status_code == 200 and r.json()["transaction"]["customer_email"] != "pat@example.com"
    r = agent.post(
        f"/api/refunds/transactions/{txn}/refunds",
        json={"amount_cents": 1000, "reason_code": "GOODWILL", "reason": "api test"},
    )
    assert r.status_code == 200, r.text
    assert (
        login("auditor")
        .post(
            f"/api/refunds/transactions/{txn}/refunds",
            json={"amount_cents": 1, "reason_code": "GOODWILL", "reason": "x y z"},
        )
        .status_code
        == 403
    )
    assert login("flags.engineer").get("/api/refunds/requests").status_code == 403


def test_contractor_region_row_scope(login):
    eu, us = make_txn(region="EU"), make_txn(region="US")
    eu_rid, us_rid = request(eu, 500), request(us, 700)
    casey = login("support.contractor")

    txns = casey.get("/api/refunds/transactions").json()
    assert {t["id"] for t in txns["items"]} == {eu} and txns["total"] == 1
    assert casey.get("/api/refunds/transactions", params={"q": "Test"}).json()["total"] == 1
    assert casey.get(f"/api/refunds/transactions/{eu}").status_code == 200
    assert casey.get(f"/api/refunds/transactions/{us}").status_code == 404
    body = {"amount_cents": 100, "reason_code": "GOODWILL", "reason": "out of scope"}
    assert casey.post(f"/api/refunds/transactions/{us}/refunds", json=body).status_code == 404
    with session_scope() as db:
        assert (
            db.execute(
                select(func.count()).select_from(Refund).where(Refund.transaction_id == us)
            ).scalar_one()
            == 1
        )

    reqs = casey.get("/api/refunds/requests").json()
    assert {r["id"] for r in reqs["items"]} == {eu_rid} and reqs["total"] == 1
    assert casey.get(f"/api/refunds/requests/{eu_rid}").status_code == 200
    assert casey.get(f"/api/refunds/requests/{us_rid}").status_code == 404
    assert casey.get(f"/api/refunds/requests/{us_rid}/audit").status_code == 404
    assert sum(s["count"] for s in casey.get("/api/refunds/stats").json().values()) == 1

    agent = login("support.agent")
    assert agent.get("/api/refunds/transactions").json()["total"] == 2
    assert agent.get(f"/api/refunds/requests/{us_rid}").status_code == 200
    assert sum(s["count"] for s in agent.get("/api/refunds/stats").json().values()) == 2


def test_missing_region_sees_nothing():
    txn = make_txn(region="EU")
    p = dataclasses.replace(principal("support.contractor"), region=None)
    with session_scope() as db, pytest.raises(NotFound):
        service.get_txn(db, p, txn)
    with session_scope() as db, pytest.raises(NotFound):
        service.request_refund(db, p, txn, 100, "GOODWILL", "no region")


def test_seed_100k_fast():
    import time

    from app.tools.refunds.seed import seed

    t = time.time()
    with session_scope() as db:
        seed(db, 1.0)
    assert time.time() - t < 90
    with session_scope() as db:
        assert db.execute(select(func.count()).select_from(Transaction)).scalar_one() == 100_000
