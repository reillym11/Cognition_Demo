from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.foundation import approvals
from app.foundation.authz import Principal, require
from app.foundation.db import get_db
from app.tools.flags import service
from app.tools.flags.models import Flag, FlagEnv

router = APIRouter(prefix="/api/flags", tags=["flags"])


class CreateBody(BaseModel):
    key: str
    description: str = ""
    owner: str = ""
    reason: str | None = None


class EnvBody(BaseModel):
    enabled: bool
    rollout_pct: int
    rules: list[dict[str, Any]] = Field(default_factory=list)
    default_value: bool = False
    reason: str | None = None


@router.get("")
def list_flags(
    p: Principal = Depends(require("flags.read")),
    db: Session = Depends(get_db),
    q: str | None = None,
    stale: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    stmt = select(Flag)
    if q:
        stmt = stmt.where(Flag.key.ilike(f"%{q.strip()}%"))
    if stale:
        stmt = stmt.where(Flag.key.in_([s["key"] for s in service.stale_flags(db)]))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    flags = (
        db.execute(stmt.order_by(Flag.key).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    )
    envs: dict[int, dict[str, FlagEnv]] = {}
    for e in db.execute(select(FlagEnv).where(FlagEnv.flag_id.in_([f.id for f in flags]))).scalars():
        envs.setdefault(e.flag_id, {})[e.env] = e
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [service.flag_dict(f, envs.get(f.id, {})) for f in flags],
    }


@router.post("")
def create(
    body: CreateBody, p: Principal = Depends(require("flags.create")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    f = service.create_flag(db, p, body.key, body.description, body.owner, body.reason)
    return service.flag_dict(f, service.envs_for(db, f.id))


@router.get("/evaluate")
def evaluate(
    key: str,
    env: str,
    default: bool,
    p: Principal = Depends(require("flags.evaluate")),
    db: Session = Depends(get_db),
    user_id: str | None = None,
    region: str | None = None,
    plan: str | None = None,
    email_domain: str | None = None,
) -> dict[str, Any]:
    ctx = {
        k: v
        for k, v in {"user_id": user_id, "region": region, "plan": plan, "email_domain": email_domain}.items()
        if v
    }
    return service.evaluate(db, key, env, ctx, default)


@router.get("/stale")
def stale(
    p: Principal = Depends(require("flags.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return service.stale_flags(db)


@router.get("/{key}")
def get_flag(
    key: str, p: Principal = Depends(require("flags.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    f = service.get_flag(db, key)
    req = approvals.open_for_subject(db, service.RES, f"{f.key}:prod")
    return {
        "flag": service.flag_dict(f, service.envs_for(db, f.id)),
        "pending_prod": approvals.to_dict(req, approvals.decisions_for(db, req.id), p) if req else None,
        "pending_payload": req.payload if req else None,
        "history": service.history(db, f.id),
        "can": {"edit": p.has("flags.edit"), "prod": p.has("flags.prod.request")},
    }


@router.put("/{key}/envs/{env}")
def change(
    key: str,
    env: str,
    body: EnvBody,
    p: Principal = Depends(require("flags.edit")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.change(db, p, key, env, body.model_dump(exclude={"reason"}), body.reason)
