"""~60 synthetic flags across envs, including some stale (100% in prod for weeks)."""

import random
from datetime import timedelta

from sqlalchemy.orm import Session

from app.foundation.db import utcnow
from app.tools.flags.models import ENVS, Flag, FlagEnv

AREAS = [
    "checkout",
    "kyc",
    "refunds",
    "payouts",
    "onboarding",
    "statements",
    "cards",
    "search",
    "alerts",
    "support",
]
THINGS = ["new-flow", "v2-api", "beta-ui", "fast-path", "dark-launch", "redesign"]


def seed(db: Session, scale: float = 1.0) -> None:
    rng = random.Random(11)
    now = utcnow()
    keys = sorted({f"{rng.choice(AREAS)}.{rng.choice(THINGS)}" for _ in range(200)})[
        : max(5, int(60 * scale))
    ]
    for i, key in enumerate(keys):
        f = Flag(
            key=key,
            description=f"Synthetic flag for {key.replace('.', ' ')}",
            owner=rng.choice(["Engineer", "Product Manager"]),
            created_by="seed",
            created_at=now - timedelta(days=rng.randint(5, 200)),
        )
        db.add(f)
        db.flush()
        for env in ENVS:
            pct = {
                "dev": 100,
                "staging": rng.choice([50, 100]),
                "prod": rng.choice([0, 0, 5, 25, 50, 100, 100]),
            }[env]
            full = pct == 100
            since = now - timedelta(days=rng.choice([3, 20, 45])) if full else None
            db.add(
                FlagEnv(
                    flag_id=f.id,
                    env=env,
                    enabled=pct > 0,
                    rollout_pct=pct,
                    rules=[{"attribute": "region", "op": "in", "values": ["US"]}]
                    if (env == "prod" and i % 9 == 0 and not full)
                    else [],
                    default_value=False,
                    version=1,
                    full_rollout_since=since,
                    updated_by="seed",
                    updated_at=since or now,
                )
            )
