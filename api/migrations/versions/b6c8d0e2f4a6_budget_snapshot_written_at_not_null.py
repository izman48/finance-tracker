"""Budget snapshots: written_at NOT NULL (eng-a on #160).

Safe on live rows: every row was inserted with the server default now(), so
none is NULL; any that were are set to now() first. The previous release
never sets written_at, so the server default keeps filling it.

Revision ID: b6c8d0e2f4a6
Revises: a5b7c9d1e3f5
Create Date: 2026-10-12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c8d0e2f4a6"
down_revision: Union[str, None] = "a5b7c9d1e3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE budget_cycle_snapshots SET written_at = now() WHERE written_at IS NULL")
    op.alter_column("budget_cycle_snapshots", "written_at", existing_type=sa.DateTime(timezone=True),
                    existing_server_default=sa.func.now(), nullable=False)


def downgrade() -> None:
    op.alter_column("budget_cycle_snapshots", "written_at", existing_type=sa.DateTime(timezone=True),
                    existing_server_default=sa.func.now(), nullable=True)
