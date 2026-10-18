"""Foundation tables. Tool tables live in app/tools/<key>/models.py."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.foundation.db import Base, utcnow


class UserSession(Base):
    __tablename__ = "user_sessions"
    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    oid: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    roles: Mapped[list[str]] = mapped_column(JSONB)
    region: Mapped[str | None] = mapped_column(String(16))
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    roles_checked_at: Mapped[datetime] = mapped_column(default=utcnow)
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(String(200))


class OidcLoginState(Base):
    __tablename__ = "oidc_login_states"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str] = mapped_column(String(128))
    browser_binding: Mapped[str] = mapped_column(String(64))
    return_to: Mapped[str] = mapped_column(String(300), default="/")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(40), index=True)
    occurred_at: Mapped[datetime]
    actor_id: Mapped[str] = mapped_column(String(100), index=True)
    actor_name: Mapped[str] = mapped_column(String(200))
    actor_roles: Mapped[list[str]] = mapped_column(JSONB)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    retention_class: Mapped[str] = mapped_column(String(40))
    retain_until: Mapped[datetime]
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    __table_args__ = (Index("ix_audit_resource", "resource", "resource_id"),)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)
    subject_type: Mapped[str] = mapped_column(String(60))
    subject_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    requested_by: Mapped[str] = mapped_column(String(100))
    requested_by_name: Mapped[str] = mapped_column(String(200))
    request_reason: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    requirement: Mapped[dict[str, Any]] = mapped_column(JSONB)
    current_stage: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    closed_at: Mapped[datetime | None]
    __table_args__ = (Index("ix_approval_subject", "subject_type", "subject_id"),)


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("approval_requests.id"), index=True)
    stage: Mapped[int] = mapped_column(Integer)
    decided_by: Mapped[str] = mapped_column(String(100))
    decided_by_name: Mapped[str] = mapped_column(String(200))
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(default=utcnow)
    __table_args__ = (UniqueConstraint("request_id", "decided_by", name="uq_decision_once_per_user"),)


class PolicyValue(Base):
    __tablename__ = "policy_values"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer)
    value: Mapped[Any] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    approval_request_id: Mapped[int | None]
    __table_args__ = (UniqueConstraint("key", "version", name="uq_policy_key_version"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(String(80))
    locked_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
    __table_args__ = (
        Index(
            "uq_jobs_dedupe_active",
            "dedupe_key",
            unique=True,
            postgresql_where="dedupe_key IS NOT NULL AND status IN ('queued','running')",
        ),
    )


class StoredFile(Base):
    __tablename__ = "stored_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(100))
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)
    retain_until: Mapped[datetime]
    purpose: Mapped[str] = mapped_column(String(60))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
