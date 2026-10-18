from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.foundation.db import Base, utcnow


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_email: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(20))
    product: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(40), index=True)
    regulatory: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    unfair_treatment: Mapped[bool] = mapped_column(Boolean, default=False)
    root_cause: Mapped[str | None] = mapped_column(String(60))
    compliance_notes: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(10), index=True, default="open")
    stage_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stage_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(80), index=True)
    assigned_name: Mapped[str | None] = mapped_column(String(200))
    checks: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    completers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    related: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
