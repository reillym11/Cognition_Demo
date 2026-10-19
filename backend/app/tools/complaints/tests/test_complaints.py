import itertools

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import func, insert, select

from app.foundation.db import session_scope, utcnow
from app.foundation.errors import Conflict, Forbidden, Invalid
from app.tools.complaints import service
from app.tools.complaints.models import Complaint
from testing import principal

_SEQ = itertools.count(1)


def make(**kw) -> int:
    now = utcnow()
    with session_scope() as db:
        return db.execute(
            insert(Complaint)
            .values(
                ref=f"CMP-T{next(_SEQ)}",
                customer_name="Jane Doe",
                customer_email="jane@example.com",
                channel="email",
                description="desc",
                stage="intake",
                status="open",
                stage_entered_at=now,
                stage_due_at=now,
                checks={},
                completers={},
                related=[],
                received_at=now,
                regulatory=False,
                unfair_treatment=False,
                **kw,
            )
            .returning(Complaint.id)
        ).scalar_one()


def step(cid: int, who: str, fields: dict | None = None, checks: dict | None = None) -> str:
    with session_scope() as db:
        if fields or checks:
            service.update(db, principal(who), cid, fields or {}, checks or {}, "filling in")
        return service.advance(db, principal(who), cid, "stage complete").stage


def run_to_resolve(cid: int, regulatory: bool) -> None:
    with session_scope() as db:
        service.claim(db, principal("hana.handler"), cid)
    step(cid, "hana.handler", {"product": "fees", "summary": "fee"})
    step(cid, "hana.handler", {"category": "fees_charges", "regulatory": regulatory})
    step(
        cid,
        "hana.handler",
        {"root_cause": "process.manual_error"},
        {"contacted_customer": True, "reviewed_records": True},
    )


def test_happy_path_closes_and_audits():
    cid = make()
    run_to_resolve(cid, False)
    assert step(cid, "hana.handler", {"resolution": "credited"}) == "respond"
    step(cid, "hana.handler", {"response_text": "letter"}, {"response_sent": True})
    with session_scope() as db:
        c = service.get(db, cid)
        assert (
            c.status == "closed"
            and c.closed_at
            and set(c.completers) == {"intake", "classify", "investigate", "resolve", "respond"}
        )


def test_required_fields_and_checklist_block_advance():
    cid = make()
    with session_scope() as db:
        service.claim(db, principal("hana.handler"), cid)
    with session_scope() as db, pytest.raises(Invalid, match="product"):
        service.advance(db, principal("hana.handler"), cid, "too early")
    step(cid, "hana.handler", {"product": "fees", "summary": "s"})
    step(cid, "hana.handler", {"category": "delay"})
    with session_scope() as db:
        service.update(db, principal("hana.handler"), cid, {"root_cause": "system.outage"}, {}, "rc")
    with session_scope() as db, pytest.raises(Invalid, match="checklist:contacted_customer"):
        service.advance(db, principal("hana.handler"), cid, "missing checks")


def test_regulatory_branch_needs_compliance_and_different_person(directory):
    cid = make()
    run_to_resolve(cid, True)
    assert step(cid, "hana.handler", {"resolution": "credited"}) == "compliance_review"
    with session_scope() as db, pytest.raises(Forbidden):
        service.update(db, principal("hana.handler"), cid, {"compliance_notes": "fine"}, {}, "self review")
    with session_scope() as db, pytest.raises(Invalid):
        service.advance(db, principal("cora.compliance"), cid, "no notes yet")
    assert step(cid, "cora.compliance", {"compliance_notes": "Checked against conduct rules"}) == "respond"
    with session_scope() as db:
        assert service.get(db, cid).assigned_to == principal("hana.handler").oid


def test_compliance_review_freezes_reviewed_fields():
    cid = make()
    run_to_resolve(cid, True)
    step(cid, "hana.handler", {"resolution": "credited"})
    for f in ({"resolution": "self-approved"}, {"root_cause": "customer.not_upheld"}, {"summary": "x"}):
        with session_scope() as db, pytest.raises(Invalid, match="not editable"):
            service.update(db, principal("cora.compliance"), cid, f, {}, "reviewer edit")
    step(cid, "cora.compliance", {"compliance_notes": "Checked against conduct rules"})
    for f in (
        {"resolution": "no redress"},
        {"root_cause": "customer.not_upheld"},
        {"category": "delay"},
        {"product": "cards"},
        {"summary": "x"},
        {"compliance_notes": "rewritten"},
    ):
        with session_scope() as db, pytest.raises(Invalid, match="not editable"):
            service.update(db, principal("hana.handler"), cid, f, {}, "post-review edit")
    step(cid, "hana.handler", {"response_text": "letter"}, {"response_sent": True})
    with session_scope() as db:
        c = service.get(db, cid)
        assert c.status == "closed" and c.resolution == "credited" and c.root_cause == "process.manual_error"


def test_unreviewed_case_keeps_earlier_fields_editable():
    cid = make()
    run_to_resolve(cid, False)
    step(cid, "hana.handler", {"resolution": "credited"})
    with session_scope() as db:
        service.update(db, principal("hana.handler"), cid, {"resolution": "credited + apology"}, {}, "fix")


def test_hand_back_skips_investigator_who_lost_work_permission(directory):
    from app.foundation.adapters.directory import DirectoryEntry

    cid = make()
    run_to_resolve(cid, True)
    step(cid, "hana.handler", {"resolution": "credited"})
    oid = principal("hana.handler").oid
    directory.entries[oid] = DirectoryEntry(oid, True, ["Audit.Auditor"])
    assert step(cid, "cora.compliance", {"compliance_notes": "Checked against conduct rules"}) == "respond"
    with session_scope() as db:
        assert service.get(db, cid).assigned_to is None


def test_stale_assignment_without_work_permission_cannot_progress(login):
    auditor = principal("aud.auditor")
    cid = make(assigned_to=auditor.oid, assigned_name=auditor.name)
    with session_scope() as db, pytest.raises(Forbidden):
        service.update(db, auditor, cid, {"summary": "x"}, {}, "stale")
    with session_scope() as db, pytest.raises(Forbidden):
        service.advance(db, auditor, cid, "stale")
    c = login("aud.auditor")
    assert c.patch(f"/api/complaints/{cid}", json={"fields": {"summary": "x"}}).status_code == 403
    assert c.post(f"/api/complaints/{cid}/advance", json={"reason": "stale"}).status_code == 403
    with session_scope() as db:
        assert service.get(db, cid).summary is None


def test_compliance_separation_from_investigator():
    from app.foundation import workflow

    data = {"regulatory": True, "compliance_notes": "x"}
    with pytest.raises(Forbidden, match="someone else"):
        workflow.advance(
            service.WF,
            "compliance_review",
            data,
            {},
            {"investigate": principal("cora.compliance").oid},
            principal("cora.compliance"),
            utcnow(),
        )


def test_claim_race_and_worker_rules():
    cid = make()
    with session_scope() as db:
        service.claim(db, principal("hana.handler"), cid)
    with session_scope() as db, pytest.raises(Conflict):
        service.claim(db, principal("hugo.handler"), cid)
    with session_scope() as db, pytest.raises(Forbidden):
        service.update(db, principal("hugo.handler"), cid, {"summary": "x"}, {}, "not mine")
    with session_scope() as db, pytest.raises(Invalid):
        service.update(db, principal("hana.handler"), cid, {"resolution": "skip ahead"}, {}, "future stage")
    with session_scope() as db, pytest.raises(Invalid):
        service.update(db, principal("hana.handler"), cid, {"product": "spaceships"}, {}, "bad value")


def test_links_and_reveal():
    cid = make()
    with session_scope() as db:
        service.claim(db, principal("hana.handler"), cid)
    with session_scope() as db, pytest.raises(Exception, match="not found"):
        service.link(db, principal("hana.handler"), cid, "refund", 999_999, "related refund")
    with session_scope() as db:
        assert service.to_dict(service.get(db, cid))["customer_name"] != "Jane Doe"
        assert (
            service.reveal(db, principal("hana.handler"), cid, "customer_name", "calling customer")
            == "Jane Doe"
        )


def test_aging_and_register(login):
    make()
    a = login("hana.handler").get("/api/complaints/aging").json()
    assert a["open"] == 1 and a["buckets"][0]["count"] == 1
    assert (
        login("hana.handler")
        .get("/api/complaints/register.csv", params={"reason": "monthly register"})
        .status_code
        == 403
    )
    r = login("cora.compliance").get("/api/complaints/register.csv", params={"reason": "monthly register"})
    assert r.status_code == 200 and "Jane Doe" not in r.text and "CMP-T" in r.text
    assert login("erin.engineer").get("/api/complaints").status_code == 403


def test_seed_volume():
    from app.tools.complaints import seed

    with session_scope() as db:
        seed.seed(db, 1.0)
    with session_scope() as db:
        n = db.execute(select(func.count()).select_from(Complaint)).scalar_one()
        reg = db.execute(select(func.count()).where(Complaint.regulatory)).scalar_one()
    assert 5_000 <= n <= 10_000 and 0.08 < reg / n < 0.16


@settings(max_examples=100, deadline=None)
@given(st.booleans(), st.booleans())
def test_property_path_shape(reg, unfair):
    keys = [s.key for s in service.WF.path({"regulatory": reg, "unfair_treatment": unfair})]
    assert keys[0] == "intake" and keys[-1] == "respond"
    assert ("compliance_review" in keys) == (reg or unfair)
    if reg or unfair:
        assert keys.index("compliance_review") == keys.index("resolve") + 1
