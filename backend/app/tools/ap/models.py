from datetime import date, datetime
from typing import Any

from sqlalchemy import ARRAY, JSON, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.foundation.db import Base, utcnow


class Vendor(Base):
    __tablename__ = "ap_vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    phone_on_file: Mapped[str] = mapped_column(String(40))
    bank_name: Mapped[str] = mapped_column(String(100))
    bank_account: Mapped[str] = mapped_column(String(34))
    bank_routing: Mapped[str] = mapped_column(String(20))
    bank_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PurchaseOrder(Base):
    __tablename__ = "ap_purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(30), unique=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("ap_vendors.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    invoiced_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(10), default="open")


class Invoice(Base):
    __tablename__ = "ap_invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("stored_files.id"))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), index=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("ap_vendors.id"), index=True)
    vendor_name: Mapped[str | None] = mapped_column(String(200))
    invoice_number: Mapped[str | None] = mapped_column(String(60))
    invoice_number_norm: Mapped[str | None] = mapped_column(String(60), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    po_number: Mapped[str | None] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal_cents: Mapped[int | None] = mapped_column(Integer)
    tax_cents: Mapped[int | None] = mapped_column(Integer)
    total_cents: Mapped[int | None] = mapped_column(Integer)
    remit_bank_name: Mapped[str | None] = mapped_column(String(100))
    remit_account: Mapped[str | None] = mapped_column(String(34))
    remit_routing: Mapped[str | None] = mapped_column(String(20))
    extraction: Mapped[dict[str, Any]] = mapped_column(JSON)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    match: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duplicate_of: Mapped[int | None] = mapped_column(Integer)
    approval_request_id: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[str] = mapped_column(String(80))
    verified_by: Mapped[str | None] = mapped_column(String(80))
    touched_by: Mapped[list[str]] = mapped_column(ARRAY(String(80)), default=list)
    batch_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BankChange(Base):
    __tablename__ = "ap_bank_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("ap_vendors.id"), index=True)
    new_bank_name: Mapped[str] = mapped_column(String(100))
    new_account: Mapped[str] = mapped_column(String(34))
    new_routing: Mapped[str] = mapped_column(String(20))
    source_invoice_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), index=True)
    requested_by: Mapped[str] = mapped_column(String(80))
    requested_by_name: Mapped[str] = mapped_column(String(200))
    request_reason: Mapped[str] = mapped_column(Text)
    callback_by: Mapped[str | None] = mapped_column(String(80))
    callback_notes: Mapped[str | None] = mapped_column(Text)
    approval_request_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentBatch(Base):
    __tablename__ = "ap_payment_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_by_name: Mapped[str] = mapped_column(String(200))
    count: Mapped[int] = mapped_column(Integer)
    total_cents: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
