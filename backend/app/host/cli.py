"""Ops CLI: seed, reset, audit verification/tamper demo, access matrix, OpenAPI, tool scaffolding."""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from app.foundation.settings import get_settings

ROOT = Path(__file__).resolve().parents[3]
SUPERUSER_URL = "postgresql+psycopg://postgres:postgres@localhost:54320/{db}"


def _db_name() -> str:
    return get_settings().database_url.rsplit("/", 1)[1]


def cmd_reset_db(_: argparse.Namespace) -> None:
    db = _db_name()
    eng = create_engine(SUPERUSER_URL.format(db="postgres"), isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{db}" OWNER itp_owner'))
    print(f"recreated {db}")


def cmd_seed(args: argparse.Namespace) -> None:
    from app.foundation import policy
    from app.foundation.db import session_scope
    from app.foundation.registry import get_registry

    t0 = time.time()
    with session_scope() as db:
        policy.seed_defaults(db)
    for m in sorted(get_registry().manifests, key=lambda m: m.seed_order):
        if m.seed:
            t = time.time()
            with session_scope() as db:
                m.seed(db, args.scale)
            print(f"seeded {m.key:12s} {time.time() - t:6.1f}s")
    print(f"seed done in {time.time() - t0:.1f}s")


def cmd_audit_verify(_: argparse.Namespace) -> None:
    from app.foundation import audit
    from app.foundation.db import session_scope

    bad = 0
    with session_scope() as db:
        for c in audit.chains(db):
            r = audit.verify_chain(db, c)
            status = "OK " if r.ok else "BAD"
            print(f"{status} chain={r.chain:12s} events={r.count:7d} " + (f"first_bad_seq={r.first_bad_seq} ({r.problem})" if not r.ok else f"head={r.head[:16] if r.head else ''}"))
            bad += 0 if r.ok else 1
    sys.exit(1 if bad else 0)


def cmd_audit_tamper_demo(_: argparse.Namespace) -> None:
    """Shows that even a DB superuser who bypasses the trigger can't edit history undetected."""
    from app.foundation import audit
    from app.foundation.db import session_scope

    eng = create_engine(SUPERUSER_URL.format(db=_db_name()))
    with eng.begin() as c:
        row = c.execute(text("SELECT seq, chain, reason FROM audit_events WHERE reason IS NOT NULL ORDER BY seq LIMIT 1")).first()
        if row is None:
            print("no audit events with a reason yet; run `make seed` or use the app first")
            sys.exit(2)
        seq, chain, reason = row
        print(f"1) app role attempts UPDATE on audit seq={seq} ...")
    try:
        with session_scope() as db:
            db.execute(text("UPDATE audit_events SET reason = 'edited' WHERE seq = :s"), {"s": seq})
        print("   unexpected: update succeeded")
    except Exception as e:
        print(f"   blocked: {type(e).__name__}: {str(e).splitlines()[0][:120]}")
    print("2) superuser disables the trigger and rewrites the reason ...")
    with eng.begin() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(text("UPDATE audit_events SET reason = :r WHERE seq = :s"), {"r": reason + " (tampered)", "s": seq})
    with session_scope() as db:
        r = audit.verify_chain(db, chain)
    print(f"3) verify chain={chain}: ok={r.ok} first_bad_seq={r.first_bad_seq} problem={r.problem}")
    with eng.begin() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(text("UPDATE audit_events SET reason = :r WHERE seq = :s"), {"r": reason, "s": seq})
    with session_scope() as db:
        r2 = audit.verify_chain(db, chain)
    print(f"4) restored original value; verify ok={r2.ok}")
    sys.exit(0 if (not r.ok and r2.ok) else 1)


def cmd_access_matrix(_: argparse.Namespace) -> None:
    from app.foundation.core_manifest import access_matrix_markdown
    from app.host.main import create_app

    print(access_matrix_markdown(create_app()), end="")


def cmd_openapi(_: argparse.Namespace) -> None:
    from app.host.main import create_app

    print(json.dumps(create_app().openapi(), indent=1, sort_keys=True))


def cmd_new_tool(args: argparse.Namespace) -> None:
    name = args.name
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,30}", name or ""):
        sys.exit("name must be snake_case, 3-31 chars")
    tpl = ROOT / "backend/app/host/tool_template"
    dest = ROOT / "backend/app/tools" / name
    if dest.exists():
        sys.exit(f"{dest} exists")
    dest.mkdir(parents=True)
    title = name.replace("_", " ").title()
    for f in tpl.rglob("*.tpl"):
        out = dest / f.relative_to(tpl).with_suffix("")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f.read_text().replace("__tool__", name).replace("__Title__", title))
    webdest = ROOT / "web/src/tools" / name
    webdest.mkdir(parents=True)
    for f in (ROOT / "web/src/tool_template").glob("*.tpl"):
        (webdest / f.name.removesuffix(".tpl")).write_text(f.read_text().replace("__tool__", name).replace("__Title__", title))
    print(f"created backend/app/tools/{name} and web/src/tools/{name}; next: models, migration, routes (see playbook)")


def main() -> None:
    ap = argparse.ArgumentParser(prog="itp")
    sub = ap.add_subparsers(required=True)
    sub.add_parser("reset-db").set_defaults(fn=cmd_reset_db)
    s = sub.add_parser("seed")
    s.add_argument("--scale", type=float, default=1.0)
    s.set_defaults(fn=cmd_seed)
    sub.add_parser("audit-verify").set_defaults(fn=cmd_audit_verify)
    sub.add_parser("audit-tamper-demo").set_defaults(fn=cmd_audit_tamper_demo)
    sub.add_parser("access-matrix").set_defaults(fn=cmd_access_matrix)
    sub.add_parser("openapi").set_defaults(fn=cmd_openapi)
    n = sub.add_parser("new-tool")
    n.add_argument("name")
    n.set_defaults(fn=cmd_new_tool)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
