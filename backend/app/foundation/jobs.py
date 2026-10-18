"""Postgres job queue (FOR UPDATE SKIP LOCKED). Enqueue inside a business transaction = transactional outbox."""

import logging
import os
import socket
import time
import traceback
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.foundation.datacls import redact_text
from app.foundation.db import session_scope
from app.foundation.models import Job
from app.foundation.registry import get_registry

log = logging.getLogger("itp.jobs")


def enqueue(db: Session, kind: str, payload: dict[str, Any] | None = None, *, run_at: datetime | None = None,
            dedupe_key: str | None = None, max_attempts: int = 5) -> None:
    if kind not in get_registry().jobs:
        raise ValueError(f"unknown job kind {kind!r}")
    stmt = insert(Job).values(kind=kind, payload=payload or {}, run_at=run_at or datetime.now(UTC),
                              dedupe_key=dedupe_key, max_attempts=max_attempts, status="queued", attempts=0,
                              created_at=datetime.now(UTC))
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"],
                                           index_where=text("dedupe_key IS NOT NULL AND status IN ('queued','running')"))
    db.execute(stmt)


def _claim(worker_id: str) -> Job | None:
    with session_scope() as db:
        sub = (select(Job.id).where(Job.status == "queued", Job.run_at <= func.now())
               .order_by(Job.run_at, Job.id).limit(1).with_for_update(skip_locked=True).scalar_subquery())
        row = db.execute(
            update(Job).where(Job.id == sub)
            .values(status="running", locked_by=worker_id, locked_at=func.now(), attempts=Job.attempts + 1)
            .returning(Job)
        ).scalar_one_or_none()
        if row is not None:
            db.expunge(row)
        return row


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2 ** attempts, 300))


def run_one(worker_id: str = "inline") -> bool:
    job = _claim(worker_id)
    if job is None:
        return False
    handler = get_registry().jobs.get(job.kind)
    try:
        if handler is None:
            raise RuntimeError(f"no handler for {job.kind}")
        with session_scope() as db:
            handler(db, job.payload)
            db.execute(update(Job).where(Job.id == job.id).values(status="succeeded", finished_at=func.now(), last_error=None))
    except Exception as e:
        err = redact_text(f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")[:2000]
        dead = job.attempts >= job.max_attempts
        with session_scope() as db:
            db.execute(update(Job).where(Job.id == job.id).values(
                status="dead" if dead else "queued", last_error=err, locked_by=None,
                run_at=datetime.now(UTC) + _backoff(job.attempts), finished_at=func.now() if dead else None))
        log.warning("job.failed", extra={"job_id": job.id, "kind": job.kind, "attempt": job.attempts, "dead": dead})
    return True


def run_until_idle(max_jobs: int = 10_000, include_future: bool = False) -> int:
    """Test/demo helper: drain ready jobs synchronously."""
    n = 0
    while n < max_jobs:
        if include_future:
            with session_scope() as db:
                db.execute(update(Job).where(Job.status == "queued").values(run_at=func.now()))
        if not run_one():
            break
        n += 1
    return n


def reclaim_stuck(older_than: timedelta = timedelta(minutes=5)) -> int:
    with session_scope() as db:
        res = db.execute(update(Job).where(Job.status == "running", Job.locked_at < datetime.now(UTC) - older_than)
                         .values(status="queued", locked_by=None))
        return res.rowcount or 0  # type: ignore[attr-defined]


def schedule_due(last_run: dict[str, float]) -> None:
    now = time.time()
    for m in get_registry().manifests:
        for sch in m.schedules:
            if now - last_run.get(sch.job_kind, 0) >= sch.every_seconds:
                with session_scope() as db:
                    enqueue(db, sch.job_kind, {}, dedupe_key=f"schedule:{sch.job_kind}")
                last_run[sch.job_kind] = now


def worker_loop(poll_seconds: float, scheduler: bool = True) -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    last_run: dict[str, float] = {}
    log.info("worker.start", extra={"worker": worker_id})
    while True:
        if scheduler:
            schedule_due(last_run)
            if int(time.time()) % 60 == 0:
                reclaim_stuck()
        if not run_one(worker_id):
            time.sleep(poll_seconds)


def summary(db: Session) -> dict[str, Any]:
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())  # type: ignore[arg-type]
    by_kind = [
        {"kind": k, "status": s, "count": c}
        for k, s, c in db.execute(select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)
                                  .order_by(Job.kind)).all()
    ]
    return {"counts": counts, "by_kind": by_kind}


def to_dict(j: Job) -> dict[str, Any]:
    return {"id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts,
            "run_at": j.run_at.isoformat(), "last_error": j.last_error, "created_at": j.created_at.isoformat(),
            "finished_at": j.finished_at.isoformat() if j.finished_at else None, "payload": j.payload}
