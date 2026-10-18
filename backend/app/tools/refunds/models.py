from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.foundation.db import Base, utcnow

# Statuses that hold part of the captured amount. Pending/unknown refunds count, so concurrent or
# in-flight requests can never push the total past what was captured.
RESERVING = ("pending_approval", "approved", "unknown", "succeeded")
STATUSES = (*RESERVING, "rejected", "failed")


class Transaction(Base):
    __tablename__ = "refund_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    charge_id: Mapped[str] = mapped_column(String(32), unique=True)
    merchant: Mapped[str] = mapped_column(String(100), index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_email: Mapped[str] = mapped_column(String(200))
    card_last4: Mapped[str] = mapped_column(String(4))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("refund_transactions.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), index=True)
    reason_code: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(80), index=True)
    requested_by_name: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    processor_ref: Mapped[str | None] = mapped_column(String(40))
    approval_request_id: Mapped[int | None] = mapped_column(Integer)
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_why: Mapped[str | None] = mapped_column(String(200))
    velocity_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
