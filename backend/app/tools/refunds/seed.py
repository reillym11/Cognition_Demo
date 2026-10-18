"""100k deterministic synthetic card transactions plus some refund history (fixed RNG, example.com emails)."""

import random
from datetime import timedelta

from faker import Faker
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.foundation.db import utcnow
from app.tools.refunds.models import Refund, Transaction

MERCHANTS = [
    f"{w} {s}"
    for w in ("Acme", "Northwind", "Contoso", "Fabrikam", "Globex", "Initech", "Umbrella", "Stark")
    for s in ("Market", "Travel", "Software", "Fitness", "Books")
]


def seed(db: Session, scale: float = 1.0) -> None:
    rng = random.Random(7)
    fake = Faker("en_US")
    Faker.seed(7)
    people = [(fake.name(), f"{fake.user_name()}{i}@example.com") for i in range(2000)]
    now = utcnow()
    n = int(100_000 * scale)
    txns, refunds = [], []
    for i in range(1, n + 1):
        name, email = people[rng.randrange(len(people))]
        amount = int(rng.lognormvariate(8.6, 1.0)) + 100  # skewed: most < $200, tail into thousands
        captured = now - timedelta(minutes=rng.uniform(0, 60 * 24 * 180))
        txns.append(
            {
                "id": i,
                "charge_id": f"ch_{i:07d}",
                "merchant": rng.choice(MERCHANTS),
                "customer_name": name,
                "customer_email": email,
                "card_last4": f"{rng.randint(0, 9999):04d}",
                "amount_cents": amount,
                "currency": "USD",
                "captured_at": captured,
            }
        )
        if rng.random() < 0.03:
            part = amount if rng.random() < 0.6 else rng.randint(1, amount)
            ts = captured + timedelta(days=rng.uniform(0, 10))
            refunds.append(
                {
                    "transaction_id": i,
                    "amount_cents": part,
                    "currency": "USD",
                    "status": "succeeded",
                    "reason_code": rng.choice(
                        ["DUPLICATE_CHARGE", "NOT_RECEIVED", "SERVICE_ISSUE", "GOODWILL"]
                    ),
                    "reason": "seeded history",
                    "requested_by": "seed",
                    "requested_by_name": "seed",
                    "idempotency_key": f"rf_seed_{i}",
                    "processor_ref": f"re_seed_{i}",
                    "needs_approval": part > 50_000,
                    "velocity_flag": False,
                    "attempts": 1,
                    "created_at": ts,
                    "updated_at": ts,
                    "executed_at": ts,
                }
            )
    for k in range(0, len(txns), 20_000):
        db.execute(insert(Transaction), txns[k : k + 20_000])
    if refunds:
        db.execute(insert(Refund), refunds)
    db.execute(text("SELECT setval('refund_transactions_id_seq', (SELECT max(id) FROM refund_transactions))"))
