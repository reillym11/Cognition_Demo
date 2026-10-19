from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.foundation import approvals, audit, files
from app.foundation.authz import Principal, require
from app.foundation.db import get_db
from app.foundation.errors import NotFound
from app.foundation.models import AuditEvent
from app.foundation.ratelimit import sensitive_rate_limit
from app.tools.ap import service
from app.tools.ap.models import BankChange, Invoice, PaymentBatch, PurchaseOrder, Vendor

router = APIRouter(prefix="/api/ap", tags=["ap"])


class ReasonBody(BaseModel):
    reason: str | None = None


class VerifyBody(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class BankBody(BaseModel):
    from_invoice: int | None = None
    bank_name: str = ""
    account: str = ""
    routing: str = ""
    reason: str | None = None


class CallbackBody(BaseModel):
    confirmed: bool
    notes: str | None = None


class RevealBody(BaseModel):
    field: str
    reason: str | None = None


@router.get("/invoices")
def list_invoices(
    p: Principal = Depends(require("ap.read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    s = select(Invoice)
    if status:
        s = s.where(Invoice.status == status)
    if q:
        s = s.where(
            or_(Invoice.vendor_name.ilike(f"%{q.strip()}%"), Invoice.invoice_number.ilike(f"%{q.strip()}%"))
        )
    total = db.execute(select(func.count()).select_from(s.subquery())).scalar_one()
    rows = db.execute(s.order_by(Invoice.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    return {"total": total, "page": page, "page_size": page_size, "items": [service.to_dict(i) for i in rows]}


@router.post("/invoices")
def upload(
    file: UploadFile = File(...), p: Principal = Depends(require("ap.upload")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    # sync def: FastAPI runs it in the threadpool, so parsing never blocks the event loop
    content = file.file.read(files.MAX_BYTES + 1)
    return service.to_dict(service.ingest(db, p, file.filename or "upload.pdf", content, "upload"))


@router.post("/inbox/poll")
def poll(p: Principal = Depends(require("ap.upload")), db: Session = Depends(get_db)) -> dict[str, Any]:
    before = db.execute(select(func.count()).select_from(Invoice)).scalar_one()
    service.poll_inbox(db, {})
    return {"ingested": db.execute(select(func.count()).select_from(Invoice)).scalar_one() - before}


@router.get("/stats")
def stats(p: Principal = Depends(require("ap.read")), db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.stats(db)


@router.get("/invoices/{iid}")
def detail(
    iid: int, p: Principal = Depends(require("ap.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    inv = service.get(db, iid)
    d = service.to_dict(inv)
    req = db.get(approvals.ApprovalRequest, inv.approval_request_id) if inv.approval_request_id else None
    d["approval"] = approvals.to_dict(req, approvals.decisions_for(db, req.id), p) if req else None
    v = db.get(Vendor, inv.vendor_id) if inv.vendor_id else None
    d["vendor"] = service.vendor_dict(v) if v else None
    d["po"] = None
    if inv.po_number:
        po = db.execute(
            select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number)
        ).scalar_one_or_none()
        if po:
            d["po"] = {
                "po_number": po.po_number,
                "amount_cents": po.amount_cents,
                "invoiced_cents": po.invoiced_cents,
                "status": po.status,
            }
    d["can"] = {"verify": p.has("ap.verify"), "bank_request": p.has("ap.bank.request")}
    return d


@router.get("/invoices/{iid}/file")
def invoice_file(
    iid: int, p: Principal = Depends(require("ap.read")), db: Session = Depends(get_db)
) -> Response:
    inv = service.get(db, iid)
    f, data = files.read(db, inv.file_id)
    audit.record(
        db, p, "ap.invoice.file_viewed", service.RES, inv.id, chain=service.CHAIN, after={"sha256": f.sha256}
    )
    return Response(
        data,
        media_type=f.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{f.original_name}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'",
            "Cache-Control": "no-store",
        },
    )


@router.get("/invoices/{iid}/audit")
def invoice_audit(
    iid: int, p: Principal = Depends(require("ap.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    service.get(db, iid)
    rows = db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.chain == service.CHAIN,
            AuditEvent.resource == service.RES,
            AuditEvent.resource_id == str(iid),
        )
        .order_by(AuditEvent.seq)
    ).scalars()
    return [audit.to_dict(e) for e in rows]


@router.post("/invoices/{iid}/verify")
def verify(
    iid: int, body: VerifyBody, p: Principal = Depends(require("ap.verify")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.to_dict(service.verify(db, p, iid, body.fields, body.reason))


@router.post("/invoices/{iid}/submit")
def submit(
    iid: int, body: ReasonBody, p: Principal = Depends(require("ap.verify")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.to_dict(service.submit(db, p, iid, body.reason))


@router.post("/invoices/{iid}/reject")
def reject(
    iid: int, body: ReasonBody, p: Principal = Depends(require("ap.verify")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return service.to_dict(service.reject(db, p, iid, body.reason))


@router.get("/vendors")
def vendors(
    p: Principal = Depends(require("ap.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    return [service.vendor_dict(v) for v in db.execute(select(Vendor).order_by(Vendor.name)).scalars()]


@router.post("/vendors/{vid}/reveal", dependencies=[sensitive_rate_limit])
def reveal(
    vid: int,
    body: RevealBody,
    p: Principal = Depends(require("ap.bank.reveal")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    return {"value": service.reveal_vendor(db, p, vid, body.field, body.reason)}


@router.post("/vendors/{vid}/bank-changes")
def bank_change(
    vid: int,
    body: BankBody,
    p: Principal = Depends(require("ap.bank.request")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    b = service.request_bank_change(
        db,
        p,
        vid,
        from_invoice=body.from_invoice,
        bank_name=body.bank_name,
        account=body.account,
        routing=body.routing,
        reason=body.reason,
    )
    return {"id": b.id, "status": b.status}


@router.get("/bank-changes")
def bank_changes(
    p: Principal = Depends(require("ap.read")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(select(BankChange, Vendor).join(Vendor).order_by(BankChange.id.desc()).limit(200)).all()
    return [service.bank_dict(b, v) for b, v in rows]


@router.get("/bank-changes/{bid}")
def bank_change_detail(
    bid: int, p: Principal = Depends(require("ap.read")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    b = db.get(BankChange, bid)
    if b is None:
        raise NotFound("bank change not found")
    v = db.get(Vendor, b.vendor_id)
    assert v is not None
    d = service.bank_dict(b, v)
    req = db.get(approvals.ApprovalRequest, b.approval_request_id) if b.approval_request_id else None
    d["approval"] = approvals.to_dict(req, approvals.decisions_for(db, req.id), p) if req else None
    d["current"] = service.vendor_dict(v)
    d["can"] = {
        "callback": p.has("ap.bank.callback") and b.status == "pending_callback" and b.requested_by != p.oid
    }
    return d


@router.post("/bank-changes/{bid}/callback")
def callback(
    bid: int,
    body: CallbackBody,
    p: Principal = Depends(require("ap.bank.callback")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    b = service.record_callback(db, p, bid, body.confirmed, body.notes)
    return {"id": b.id, "status": b.status}


@router.get("/batches")
def batches(
    p: Principal = Depends(require("ap.batch")), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(select(PaymentBatch).order_by(PaymentBatch.id.desc()).limit(100)).scalars()
    return [
        {
            "id": b.id,
            "count": b.count,
            "total_cents": b.total_cents,
            "sha256": b.sha256,
            "created_by": b.created_by_name,
            "created_at": b.created_at.isoformat(),
        }
        for b in rows
    ]


@router.post("/batches")
def create_batch(
    body: ReasonBody, p: Principal = Depends(require("ap.batch")), db: Session = Depends(get_db)
) -> dict[str, Any]:
    b = service.create_batch(db, p, body.reason)
    return {"id": b.id, "count": b.count, "total_cents": b.total_cents, "sha256": b.sha256}


@router.get("/batches/{bid}/file")
def batch_file(
    bid: int,
    reason: str | None = None,
    p: Principal = Depends(require("ap.batch")),
    db: Session = Depends(get_db),
) -> Response:
    b = service.batch_file(db, p, bid, reason)
    return Response(
        b.content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="payment-batch-{b.id}.csv"',
            "X-Content-SHA256": b.sha256,
            "Cache-Control": "no-store",
        },
    )
