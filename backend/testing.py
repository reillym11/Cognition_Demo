import json
import os
from collections.abc import Callable, Iterator

__all__ = ["PERSONAS", "SUPER", "app", "clean_db", "directory", "login", "principal"]
from pathlib import Path

os.environ.setdefault("ITP_DATABASE_URL", "postgresql+psycopg://itp_app:itp_app@localhost:54320/itp_test")
os.environ.setdefault(
    "ITP_OWNER_DATABASE_URL", "postgresql+psycopg://itp_owner:itp_owner@localhost:54320/itp_test"
)
os.environ.setdefault("ITP_RATE_LIMIT_DEFAULT", "100000/minute")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.foundation import auth, policy
from app.foundation.adapters.directory import DirectoryEntry, set_directory
from app.foundation.db import session_scope

ROOT = Path(__file__).resolve().parents[1]
PERSONAS = {p["username"]: p for p in json.loads((ROOT / "infra/oidc/personas.json").read_text())["personas"]}
SUPER = create_engine("postgresql+psycopg://postgres:postgres@localhost:54320/itp_test")


class MemoryDirectory:
    def __init__(self) -> None:
        self.entries = {
            p["oid"]: DirectoryEntry(p["oid"], True, p.get("roles") or [], p.get("region"))
            for p in PERSONAS.values()
        }

    def lookup(self, oid: str) -> DirectoryEntry | None:
        return self.entries.get(oid)


@pytest.fixture(scope="session")
def app():
    from app.host.main import create_app

    return create_app()


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    with SUPER.begin() as c:
        c.execute(text("SET session_replication_role = replica"))
        tables = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"
                )
            )
        ]
        c.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    with session_scope() as db:
        policy.seed_defaults(db)
    yield


@pytest.fixture(autouse=True)
def reset_rate_limits() -> Iterator[None]:
    from app.foundation.ratelimit import limiter

    limiter.reset()
    yield


@pytest.fixture
def directory() -> Iterator[MemoryDirectory]:
    d = MemoryDirectory()
    set_directory(d)
    yield d
    set_directory(None)


@pytest.fixture
def login(app, directory) -> Callable[[str], TestClient]:
    def _login(username: str) -> TestClient:
        p = PERSONAS[username]
        token, csrf = auth.create_session_for_tests(
            p["oid"], username, p["name"], p.get("roles") or [], p["region"]
        )
        c = TestClient(app)
        c.cookies.set(auth.SESSION_COOKIE, token)
        c.cookies.set(auth.CSRF_COOKIE, csrf)
        c.headers["X-CSRF-Token"] = csrf
        return c

    return _login


def principal(username: str):
    from app.foundation.authz import Principal
    from app.foundation.registry import get_registry

    p = PERSONAS[username]
    roles = frozenset(p.get("roles") or [])
    return Principal(
        oid=p["oid"],
        name=p["name"],
        username=username,
        roles=roles,
        permissions=get_registry().permissions_for(roles),
        region=p["region"],
    )
