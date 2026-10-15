"""One link set between holdings and commitments (ADR-002, T-11-3b).

Additive: a new table `commitment_links` with UNIQUE(commitment_id), so a
bill is linked to at most one loan or holding of any kind. Existing loan
links are backfilled from `liabilities.linked_commitment_id` (plaintext ids
and a flag only; no encrypted value is read or written), joined on the
commitment's user so a mismatched row is skipped, and idempotent (NOT
EXISTS). The backfill logs counts only, through the alembic logger, and
never raises at boot. `assets` and `liabilities` are not changed; the
previous release ignores the table. The downgrade drops it and restores
nothing, so no foreign key can break it; holding links are lost, and their
commitments stay as ordinary bills (cash still counted).

Revision ID: c3e5a7b9d1f4
Revises: a1b3c5d7e9f2
Create Date: 2026-10-15
"""
import logging
import uuid
from datetime import date
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e5a7b9d1f4"
down_revision: Union[str, None] = "a1b3c5d7e9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger("alembic.runtime.migration")

_SOURCE = """
    SELECT l.id, l.user_id, l.linked_commitment_id, l.commitment_created
    FROM liabilities l
    JOIN commitment_rules c ON c.id = l.linked_commitment_id AND c.user_id = l.user_id
    WHERE l.linked_commitment_id IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM commitment_links k WHERE k.commitment_id = l.linked_commitment_id)
"""


def upgrade() -> None:
    op.create_table(
        "commitment_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("commitment_id", sa.Uuid(),
                  sa.ForeignKey("commitment_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=True),
        sa.Column("liability_id", sa.Uuid(), sa.ForeignKey("liabilities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("commitment_created", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_on", sa.Date(), nullable=False),
        sa.UniqueConstraint("commitment_id", name="uq_commitment_links_commitment_id"),
        sa.UniqueConstraint("asset_id", name="uq_commitment_links_asset_id"),
        sa.UniqueConstraint("liability_id", name="uq_commitment_links_liability_id"),
        sa.CheckConstraint("(asset_id IS NULL) <> (liability_id IS NULL)", name="ck_commitment_links_one_owner"),
    )
    op.create_index("ix_commitment_links_user_id", "commitment_links", ["user_id"])
    backfill()


def backfill() -> None:
    """Give every existing loan link its row. Safe to run again."""
    bind = op.get_bind()
    linked = bind.execute(sa.text(
        "SELECT count(*) FROM liabilities WHERE linked_commitment_id IS NOT NULL"
    )).scalar()
    rows = bind.execute(sa.text(_SOURCE)).fetchall()
    links = sa.table(
        "commitment_links",
        sa.column("id", sa.Uuid()), sa.column("user_id", sa.Uuid()), sa.column("commitment_id", sa.Uuid()),
        sa.column("liability_id", sa.Uuid()), sa.column("role", sa.String()),
        sa.column("commitment_created", sa.Boolean()), sa.column("created_on", sa.Date()),
    )
    if rows:
        # Ids are made here rather than with gen_random_uuid() so the same
        # code runs on the SQLite test database.
        op.bulk_insert(links, [
            {"id": uuid.uuid4(), "user_id": _uuid(user_id), "commitment_id": _uuid(commitment_id),
             "liability_id": _uuid(liability_id), "role": "repayment",
             "commitment_created": bool(created), "created_on": date.today()}
            for liability_id, user_id, commitment_id, created in rows
        ])
    log.info("Backfilling commitment_links for loans: linked=%d inserted=%d", linked, len(rows))


def _uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def downgrade() -> None:
    op.drop_index("ix_commitment_links_user_id", table_name="commitment_links")
    op.drop_table("commitment_links")
