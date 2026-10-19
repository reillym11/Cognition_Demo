"""The 'core' tool: cross-cutting admin surfaces (audit, approvals inbox, policy, jobs, access matrix)."""

import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import IO, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, jobs, notify, policy
from app.foundation.authz import Principal, authenticated, public, require
from app.foundation.datacls import Classification
from app.foundation.db import get_db
from app.foundation.errors import Invalid, NotFound, require_reason
from app.foundation.models import ApprovalRequest, AuditEvent, Job
from app.foundation.registry import ApprovalKind, NavItem, PolicyDef, ToolManifest, get_registry

router = APIRouter(prefix="/api", tags=["core"])


@router.get("/health", dependencies=[Depends(public("liveness probe"))])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", dependencies=[Depends(public("readiness probe"))])
def ready(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.execute(select(1))
    return {"status": "ready", "tools": [m.key for m in get_registry().manifests]}


class MeOut(BaseModel):
    oid: str
    name: str
    username: str
    roles: list[str]
    permissions: list[str]
    region: str | None
    nav: list[dict[str, str]]


@router.get("/me", response_model=MeOut)
def me(p: Principal = Depends(authenticated())) -> MeOut:
    nav = []
    for m in get_registry().manifests:
        for n in m.nav:
            if p.has(n.permission):
                nav.append({"tool": m.key, "tool_name": m.name, "path": n.path, "label": n.label})
    return MeOut(
        oid=p.oid,
        name=p.name,
        username=p.username,
        roles=sorted(p.roles),
        permissions=sorted(p.permissions),
        region=p.region,
        nav=nav,
    )


# ---- approvals inbox (permission is checked per stage inside approvals.decide) ----


class DecideIn(BaseModel):
    decision: str
    reason: str


@router.get("/approvals/inbox")
def approvals_inbox(
    p: Principal = Depends(authenticated()), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "open")
        .order_by(ApprovalRequest.requested_at)
        .limit(500)
    ).scalars()
    out = []
    for r in rows:
        ok, _ = approvals.can_decide(r, p)
        if ok:
            out.append(approvals.to_dict(r, approvals.decisions_for(db, r.id), p))
    return out


@router.get("/approvals/mine")
def approvals_mine(
    p: Principal = Depends(authenticated()), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(ApprovalRequest)
        .where(ApprovalRequest.requested_by == p.oid)
        .order_by(ApprovalRequest.requested_at.desc())
        .limit(100)
    ).scalars()
    return [approvals.to_dict(r, approvals.decisions_for(db, r.id), p) for r in rows]


@router.get("/approvals/{request_id}")
def approval_get(
    request_id: int, p: Principal = Depends(authenticated()), db: Session = Depends(get_db)
) -> dict[str, Any]:
    r = db.get(ApprovalRequest, request_id)
    if r is None:
        raise NotFound("approval request not found")
    ok, _ = approvals.can_decide(r, p)
    if not (ok or r.requested_by == p.oid or p.has("core.audit.read")):
        raise NotFound("approval request not found")
    return approvals.to_dict(r, approvals.decisions_for(db, r.id), p)


@router.post("/approvals/{request_id}/decide")
def approval_decide(
    request_id: int, body: DecideIn, p: Principal = Depends(authenticated()), db: Session = Depends(get_db)
) -> dict[str, Any]:
    r = approvals.decide(db, p, request_id, body.decision, body.reason)  # type: ignore[arg-type]
    return approvals.to_dict(r, approvals.decisions_for(db, r.id), p)


# ---- audit ----


@router.get("/audit/events")
def audit_events(
    chain: str | None = None,
    resource: str | None = None,
    resource_id: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    p: Principal = Depends(require("core.audit.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conds = []
    if chain:
        conds.append(AuditEvent.chain == chain)
    if resource:
        conds.append(AuditEvent.resource == resource)
    if resource_id:
        conds.append(AuditEvent.resource_id == resource_id)
    if actor:
        conds.append(or_(AuditEvent.actor_id == actor, AuditEvent.actor_name.ilike(f"%{actor}%")))
    if action:
        conds.append(AuditEvent.action.ilike(f"{action}%"))
    where = and_(true(), *conds)
    total = db.execute(select(func.count()).select_from(AuditEvent).where(where)).scalar_one()
    rows = db.execute(
        select(AuditEvent)
        .where(where)
        .order_by(AuditEvent.seq.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars()
    return {"total": total, "page": page, "page_size": page_size, "items": [audit.to_dict(e) for e in rows]}


@router.get("/audit/verify")
def audit_verify(
    p: Principal = Depends(require("core.audit.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return [vars(audit.verify_chain(db, c)) for c in audit.chains(db)]


EVIDENCE_PACK_SPOOL_BYTES = 8 * 1024 * 1024
EVIDENCE_PACK_STREAM_ROWS = 1000


@router.get("/audit/evidence-pack")
def evidence_pack(
    request: Request,
    start: date,
    end: date,
    reason: str,
    p: Principal = Depends(require("core.audit.evidence")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    reason = require_reason(reason, "an evidence pack")
    if end < start:
        raise Invalid("end date must not be before start date", code="evidence_range_invalid")
    max_days = policy.get(db, "core.evidence_pack_max_days")
    if (end - start).days + 1 > max_days:
        raise Invalid(
            f"evidence pack range exceeds {max_days} days; split it into smaller ranges",
            code="evidence_range_too_long",
        )
    t0 = datetime.combine(start, time.min, tzinfo=UTC)
    t1 = datetime.combine(end, time.min, tzinfo=UTC) + timedelta(days=1)
    in_range = and_(AuditEvent.occurred_at >= t0, AuditEvent.occurred_at < t1)
    n_events = db.execute(select(func.count()).select_from(AuditEvent).where(in_range)).scalar_one()
    max_events = policy.get(db, "core.evidence_pack_max_events")
    if n_events > max_events:
        raise Invalid(
            f"evidence pack would contain {n_events} events (limit {max_events}); narrow the date range",
            code="evidence_too_many_events",
        )
    verification = [vars(audit.verify_chain(db, c)) for c in audit.chains(db)]
    buf = tempfile.SpooledTemporaryFile(max_size=EVIDENCE_PACK_SPOOL_BYTES)  # noqa: SIM115 - closed after streaming
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            with z.open("audit-events.jsonl", "w") as out:
                events = db.execute(
                    select(AuditEvent)
                    .where(in_range)
                    .order_by(AuditEvent.seq)
                    .execution_options(yield_per=EVIDENCE_PACK_STREAM_ROWS)
                ).scalars()
                for e in events:
                    out.write(json.dumps(audit.to_dict(e), default=str).encode() + b"\n")
            z.writestr("chain-verification.json", json.dumps(verification, indent=2, default=str))
            z.writestr("access-matrix.md", access_matrix_markdown(request.app))
            z.writestr(
                "README.txt",
                (
                    f"Evidence pack {start}..{end}, generated {datetime.now(UTC).isoformat()} by {p.username}.\n"
                    "audit-events.jsonl: every audit event in range (PII appears only as keyed fingerprints).\n"
                    "chain-verification.json: full hash-chain verification per chain at generation time.\n"
                    "access-matrix.md: roles -> permissions -> routes, generated from code.\n"
                ),
            )
        size = buf.tell()
        buf.seek(0)
    except BaseException:
        buf.close()
        raise
    audit.record(
        db,
        p,
        "audit.evidence_pack",
        "audit",
        f"{start}..{end}",
        chain="core",
        reason=reason,
        after={"events": n_events, "chains_ok": all(v["ok"] for v in verification)},
    )
    return StreamingResponse(
        _read_and_close(buf),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="evidence-{start}-{end}.zip"',
            "Content-Length": str(size),
        },
    )


def _read_and_close(f: IO[bytes], chunk: int = 64 * 1024) -> Iterator[bytes]:
    try:
        while data := f.read(chunk):
            yield data
    finally:
        f.close()


# ---- access matrix ----


def access_matrix(app: Any) -> dict[str, Any]:
    from app.foundation.authz import route_permissions

    reg = get_registry()
    routes = route_permissions(app)
    perm_routes: dict[str, list[str]] = {}
    for r in routes:
        for perm in r["permissions"]:
            perm_routes.setdefault(perm, []).append(f"{'/'.join(r['methods'])} {r['path']}")
    return {
        "roles": {role: sorted(perms) for role, perms in sorted(reg.role_permissions.items())},
        "permissions": [
            {"permission": k, "description": v, "routes": perm_routes.get(k, [])}
            for k, v in sorted(reg.permissions.items())
        ],
        "separation_of_duties": [
            "Approval requester can never approve their own request (foundation/approvals).",
            "One person decides at most once per approval request, so multi-stage approvals need distinct people.",
            "KYC: anyone who prepared/touched a case is excluded from its final decision; high-risk needs KYC.SeniorReviewer.",
            "Refunds: cumulative refunds > policy threshold (default $500) need a Finance approver other than the requester.",
            "Flags: prod changes need a Platform.Admin approval other than the requester.",
            "AP: vendor bank-detail changes need out-of-band verification plus a second approver.",
            "Policy changes (thresholds, windows, fast-lane criteria) need core.policy.approve by someone else.",
        ],
        "routes": routes,
    }


def access_matrix_markdown(app: Any) -> str:
    m = access_matrix(app)
    lines = ["# Access matrix (generated from code)", "", "## Roles → permissions", ""]
    for role, perms in m["roles"].items():
        lines.append(f"- **{role}**: " + ", ".join(f"`{x}`" for x in perms))
    lines += ["", "## Permissions → routes", "", "| Permission | Description | Routes |", "|---|---|---|"]
    for p in m["permissions"]:
        lines.append(
            f"| `{p['permission']}` | {p['description']} | {'<br>'.join(p['routes']) or '(UI/indirect)'} |"
        )
    lines += ["", "## Separation of duties", ""] + [f"- {s}" for s in m["separation_of_duties"]]
    return "\n".join(lines) + "\n"


@router.get("/access-matrix")
def access_matrix_route(
    request: Request, p: Principal = Depends(require("core.access.read"))
) -> dict[str, Any]:
    return access_matrix(request.app)


# ---- policy ----


class PolicyChangeIn(BaseModel):
    value: Any
    reason: str


@router.get("/policy")
def policy_list(
    p: Principal = Depends(require("core.policy.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return policy.list_all(db)


@router.post("/policy/{key}/change-request")
def policy_change(
    key: str,
    body: PolicyChangeIn,
    p: Principal = Depends(require("core.policy.request")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    r = policy.request_change(db, p, key, body.value, body.reason)
    return approvals.to_dict(r, [], p)


# ---- jobs admin ----


@router.get("/jobs")
def jobs_list(
    status: str | None = None,
    kind: str | None = None,
    p: Principal = Depends(require("core.jobs.read")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = select(Job).order_by(Job.id.desc()).limit(100)
    if status:
        q = q.where(Job.status == status)
    if kind:
        q = q.where(Job.kind == kind)
    return {"summary": jobs.summary(db), "items": [jobs.to_dict(j) for j in db.execute(q).scalars()]}


class RetryIn(BaseModel):
    reason: str


@router.post("/jobs/{job_id}/retry")
def jobs_retry(
    job_id: int,
    body: RetryIn,
    p: Principal = Depends(require("core.jobs.admin")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    j = db.get(Job, job_id, with_for_update=True)
    if j is None:
        raise NotFound("job not found")
    reason = require_reason(body.reason, "retrying a job")
    before = {"status": j.status, "attempts": j.attempts}
    j.status, j.attempts, j.run_at, j.finished_at = "queued", 0, datetime.now(UTC), None
    audit.record(
        db,
        p,
        "job.retry",
        "job",
        j.id,
        chain="core",
        reason=reason,
        before=before,
        after={"status": j.status, "attempts": 0},
    )
    return jobs.to_dict(j)


def _noop(db: Session, req: ApprovalRequest) -> None:
    return None


MANIFEST = ToolManifest(
    key="core",
    name="Platform",
    description="Audit log, approvals inbox, policy, background jobs, access matrix.",
    permissions={
        "core.audit.read": "Read the audit log and chain verification",
        "core.audit.evidence": "Generate audit evidence packs",
        "core.access.read": "Read the generated access / separation-of-duties matrix",
        "core.policy.read": "Read policy values",
        "core.policy.request": "Request a policy change",
        "core.policy.approve": "Approve policy changes",
        "core.jobs.read": "Read background job status",
        "core.jobs.admin": "Retry failed background jobs",
    },
    grants={
        "Audit.Auditor": [
            "core.audit.read",
            "core.audit.evidence",
            "core.access.read",
            "core.policy.read",
            "core.jobs.read",
        ],
        "Compliance.Admin": [
            "core.audit.read",
            "core.audit.evidence",
            "core.access.read",
            "core.policy.read",
            "core.policy.request",
            "core.policy.approve",
        ],
        "Platform.Admin": [
            "core.jobs.read",
            "core.jobs.admin",
            "core.policy.read",
            "core.policy.request",
            "core.policy.approve",
            "core.access.read",
            "core.audit.read",
        ],
        "Finance.Controller": ["core.policy.read", "core.policy.request", "core.policy.approve"],
        "Finance.Approver": ["core.policy.read"],
    },
    router=router,
    nav=[
        NavItem("/admin/audit", "Audit log", "core.audit.read"),
        NavItem("/admin/policy", "Policy", "core.policy.read"),
        NavItem("/admin/jobs", "Background jobs", "core.jobs.read"),
        NavItem("/admin/access", "Access matrix", "core.access.read"),
    ],
    jobs={"core.notify_teams": notify.deliver},
    approval_kinds={
        "core.policy_change": ApprovalKind(on_approved=policy.apply_approved, label="Policy change")
    },
    policies={
        "core.evidence_pack_max_days": PolicyDef(
            366, "Longest date range (days) one audit evidence pack may cover"
        ),
        "core.evidence_pack_max_events": PolicyDef(
            250_000, "Most audit events one evidence pack may contain; larger ranges must be split"
        ),
    },
    classifications={"session": {}, "audit": {}, "policy": {}, "job": {}, "approval": {}},
)
_ = Classification
