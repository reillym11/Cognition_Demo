from datetime import datetime

from sqlalchemy import ARRAY, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.foundation.db import Base, utcnow

OPEN_STATUSES = ("new", "in_review", "info_requested", "pending_decision")


class KycCase(Base):
    __tablename__ = "kyc_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    applicant_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200))
    dob: Mapped[str] = mapped_column(String(10))
    ssn: Mapped[str] = mapped_column(String(11))
    address: Mapped[str] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(2))
    region: Mapped[str] = mapped_column(String(4), index=True)
    risk_level: Mapped[str] = mapped_column(String(10), index=True)
    vendor_score: Mapped[int] = mapped_column(Integer)
    watchlist_hits: Mapped[int] = mapped_column(Integer, default=0)
    docs_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), index=True)
    requires_senior: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_to: Mapped[str | None] = mapped_column(String(100), index=True)
    assigned_name: Mapped[str | None] = mapped_column(String(200))
    # Everyone who prepared/worked the case; none of them may make the final decision.
    touched_by: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    recommendation: Mapped[str | None] = mapped_column(String(10))
    recommendation_code: Mapped[str | None] = mapped_column(String(40))
    recommended_by: Mapped[str | None] = mapped_column(String(100))
    decision: Mapped[str | None] = mapped_column(String(10))
    decision_code: Mapped[str | None] = mapped_column(String(40))
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decided_at: Mapped[datetime | None]
    qa_status: Mapped[str | None] = mapped_column(String(10), index=True)
    sla_due_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_kyc_queue", "status", "region", "sla_due_at"),)


class KycDecision(Base):
    """Immutable decision record (append-only at the DB level; retained 5 years)."""

    __tablename__ = "kyc_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("kyc_cases.id"), index=True)
    decision: Mapped[str] = mapped_column(String(10))
    reason_code: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    recommended_by: Mapped[str | None] = mapped_column(String(100))
    decided_by: Mapped[str] = mapped_column(String(100))
    decided_by_name: Mapped[str] = mapped_column(String(200))
    approval_request_id: Mapped[int | None]
    policy_version: Mapped[int | None]
    decided_at: Mapped[datetime] = mapped_column(default=utcnow)
    retain_until: Mapped[datetime]
