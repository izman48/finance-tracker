"""The one link set between holdings and commitments (ADR-002 section 3).

A commitment carries at most one holding's contribution or repayment, of any
kind: UNIQUE(commitment_id) holds across loans and holdings because loans
write a row here too (alongside `liabilities.linked_commitment_id`, which
Sprint 10 code still reads). No encrypted column: ids, role, flags and a date.
Every field is set by the server, never taken from a request.
"""
import uuid
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CONTRIBUTION = "contribution"
REPAYMENT = "repayment"


class CommitmentLink(Base):
    __tablename__ = "commitment_links"
    __table_args__ = (
        UniqueConstraint("commitment_id", name="uq_commitment_links_commitment_id"),
        UniqueConstraint("asset_id", name="uq_commitment_links_asset_id"),
        UniqueConstraint("liability_id", name="uq_commitment_links_liability_id"),
        CheckConstraint("(asset_id IS NULL) <> (liability_id IS NULL)", name="ck_commitment_links_one_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    commitment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("commitment_rules.id", ondelete="CASCADE"),
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=True,
    )
    liability_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("liabilities.id", ondelete="CASCADE"), nullable=True,
    )
    role: Mapped[str] = mapped_column(String(20))  # CONTRIBUTION or REPAYMENT
    # Opting out deletes the commitment only if the link created it.
    commitment_created: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    # The UK day the link started; contributions count from here.
    created_on: Mapped[date] = mapped_column(Date)
