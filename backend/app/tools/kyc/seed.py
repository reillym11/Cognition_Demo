"""25k deterministic synthetic KYC cases (fixed RNG; fake SSNs use the never-issued 9xx area)."""

import random
from datetime import timedelta

from faker import Faker
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.foundation.audit import RETENTION_YEARS
from app.foundation.db import utcnow
from app.tools.kyc.models import KycCase, KycDecision

ANALYSTS = [
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "00000000-0000-4000-8000-000000000003",
]
SLA = {"low": 72, "medium": 48, "high": 24}


def seed(db: Session, scale: float = 1.0) -> None:
    rng = random.Random(42)
    fake = Faker("en_US")
    Faker.seed(42)
    now = utcnow()
    n = int(25_000 * scale)
    cases, decisions = [], []
    for i in range(1, n + 1):
        risk = rng.choices(["low", "medium", "high"], [0.6, 0.3, 0.1])[0]
        score = {"low": rng.randint(0, 35), "medium": rng.randint(30, 70), "high": rng.randint(65, 100)}[risk]
        hits = 0 if risk == "low" and rng.random() < 0.95 else rng.choice([0, 0, 1, 2])
        docs = rng.random() < (0.9 if risk == "low" else 0.7)
        created = now - timedelta(hours=rng.uniform(0, 24 * 120))
        region = "EU" if rng.random() < 0.15 else "US"
        open_ = created > now - timedelta(days=6) or rng.random() < 0.04
        status, decision, code, decided_by, decided_at = "new", None, None, None, None
        if not open_:
            status = rng.choices(["approved", "rejected", "auto_cleared"], [0.55, 0.15, 0.3])[0]
            decided_at = created + timedelta(hours=rng.uniform(1, 60))
            if status == "auto_cleared":
                decision, code, decided_by = "approve", "AUTO_CLEAR", "system:kyc-fastlane"
            else:
                decision = "approve" if status == "approved" else "reject"
                code = rng.choice(
                    ["DOCS_VERIFIED", "RISK_ACCEPTABLE"]
                    if decision == "approve"
                    else ["ID_MISMATCH", "INCOMPLETE_DOCS", "WATCHLIST_MATCH"]
                )
                decided_by = rng.choice(ANALYSTS)
        cases.append(
            {
                "id": i,
                "ref": f"KYC-{i:06d}",
                "applicant_name": fake.name(),
                "email": fake.free_email(),
                "dob": fake.date_of_birth(minimum_age=18, maximum_age=90).isoformat(),
                "ssn": f"9{rng.randint(0, 99):02d}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}",
                "address": fake.address().replace("\n", ", "),
                "country": "DE" if region == "EU" else "US",
                "region": region,
                "risk_level": risk,
                "vendor_score": score,
                "watchlist_hits": hits,
                "docs_verified": docs,
                "status": status,
                "requires_senior": False,
                "assigned_to": None,
                "assigned_name": None,
                "touched_by": [],
                "recommendation": None,
                "recommendation_code": None,
                "recommended_by": None,
                "decision": decision,
                "decision_code": code,
                "decided_by": decided_by,
                "decided_at": decided_at,
                "qa_status": None,
                "sla_due_at": created + timedelta(hours=SLA[risk]),
                "created_at": created,
                "updated_at": decided_at or created,
            }
        )
        if decided_by and decided_at:
            decisions.append(
                {
                    "case_id": i,
                    "decision": decision,
                    "reason_code": code,
                    "reason": "seeded history",
                    "recommended_by": None,
                    "decided_by": decided_by,
                    "decided_by_name": decided_by,
                    "approval_request_id": None,
                    "policy_version": None,
                    "decided_at": decided_at,
                    "retain_until": decided_at + timedelta(days=365 * RETENTION_YEARS["kyc_decision"]),
                }
            )
    db.execute(insert(KycCase), cases)
    db.execute(insert(KycDecision), decisions)
    db.execute(
        __import__("sqlalchemy").text("SELECT setval('kyc_cases_id_seq', (SELECT max(id) FROM kyc_cases))")
    )
