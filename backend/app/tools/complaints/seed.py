"""~8,000 synthetic complaints spread across stages; ~12% regulatory/unfair-treatment."""

import random
from datetime import timedelta

from faker import Faker
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.foundation.db import utcnow
from app.tools.complaints import service
from app.tools.complaints.models import Complaint

SUMMARIES = [
    "Charged a fee I was not told about",
    "Refund taking too long",
    "Card blocked without notice",
    "Could not reach support",
    "Payout delayed",
    "Disputed transaction not resolved",
    "Onboarding documents rejected",
    "Rude agent on call",
]


def seed(db: Session, scale: float = 1.0) -> None:
    rng = random.Random(7)
    fake = Faker()
    Faker.seed(7)
    now = utcnow()
    n = max(50, int(8_000 * scale))
    rows = []
    for i in range(n):
        received = now - timedelta(hours=rng.randint(1, 24 * 120))
        reg = rng.random() < 0.12
        data = {
            "product": rng.choice(service.PRODUCTS),
            "summary": rng.choice(SUMMARIES),
            "category": rng.choice(service.CATEGORIES),
            "regulatory": reg,
            "unfair_treatment": reg and rng.random() < 0.4,
            "root_cause": rng.choice(sorted(service.ALL_ROOT_CAUSES)),
            "compliance_notes": "Reviewed against conduct rules; no further action" if reg else None,
            "resolution": "Goodwill credit applied and process corrected",
            "response_text": "Final response letter sent",
        }
        path = [s.key for s in service.WF.path(data)]
        age_days = (now - received).days
        progress = min(len(path), int(age_days / 12) + rng.randint(0, 2))
        closed = progress >= len(path)
        stage = path[-1] if closed else path[progress]
        filled = set(path[:progress]) if not closed else set(path)
        row = {
            f: (
                v
                if any(f in service.STAGE_FIELDS[s] for s in filled)
                else (False if isinstance(v, bool) else None)
            )
            for f, v in data.items()
        }
        entered = received + timedelta(days=min(age_days, progress * 10))
        sla = service.WF.stage(stage).sla_hours
        rows.append(
            {
                "ref": f"CMP-{100000 + i}",
                "customer_name": fake.name(),
                "customer_email": f"c{i}@example.com",
                "channel": rng.choice(service.CHANNELS),
                "description": fake.paragraph(nb_sentences=3),
                **row,
                "stage": stage,
                "status": "closed" if closed else "open",
                "stage_entered_at": entered,
                "stage_due_at": entered + timedelta(hours=sla * rng.choice([0.5, 1, 1, 3])),
                "assigned_to": None,
                "assigned_name": None,
                "checks": {},
                "completers": {},
                "related": [],
                "received_at": received,
                "closed_at": entered if closed else None,
                "updated_at": entered,
            }
        )
    for i in range(0, len(rows), 5_000):
        db.execute(insert(Complaint), rows[i : i + 5_000])
