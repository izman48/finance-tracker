"""Audit trail and idempotency records for Claude's planning writes (T-08-3b).

`AuditEntry` is append-only: rows are inserted and never deleted, and the
only later change is `undone_at` on a write when an undo row (kind `undo`)
is added for it. The label and the before/after values copy names and
amounts from DEK-encrypted columns, so they are DEK-encrypted too. Who made
the change (`grant_id`, `client_id`) comes from the verified token.

`WriteIdempotency` makes a retried write return its first result. The
unique (user_id, key) row is inserted before the change, in the same
transaction, so two workers can't both apply. It stores a keyed hash of the
request and the audit id, never the payload.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.encryption import UserEncryptedString

AUDIT_KIND_WRITE = "write"
AUDIT_KIND_UNDO = "undo"


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    __table_args__ = (Index("ix_audit_entries_user_created", "user_id", "created_at", "id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))  # write | undo
    tool: Mapped[str] = mapped_column(String(50))
    target_kind: Mapped[str] = mapped_column(String(20))  # planned_event | commitment
    target_id: Mapped[uuid.UUID]
    target_label: Mapped[str] = mapped_column(UserEncryptedString)
    # JSON list of {"field", "before", "after"}, encrypted as one value.
    changes: Mapped[str] = mapped_column(UserEncryptedString)
    # A write whose target didn't exist before (undo soft-deletes it).
    created_target: Mapped[bool] = mapped_column(default=False, server_default=false())
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    undoes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("audit_entries.id"), nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set in Python (microseconds) rather than by the database, so writes in
    # one transaction or second still order newest first for the list.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now()
    )


class WriteIdempotency(Base):
    __tablename__ = "write_idempotency"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_write_idempotency_user_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    audit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("audit_entries.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
