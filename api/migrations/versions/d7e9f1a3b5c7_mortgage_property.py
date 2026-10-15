"""A mortgage can name its property (T-12-6b).

Additive and schema-only: `liabilities.property_asset_id`, a plaintext FK to
assets, ON DELETE SET NULL, nullable and indexed. It is read only for the
house equity line (display only), so nothing moves and the previous release
ignores it. Downgrade drops it (rollback: downgrade first, then revert); a
mortgage then just loses its property, and no total changes.

Revision ID: d7e9f1a3b5c7
Revises: e6b8d0f2a4c7
Create Date: 2026-10-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e9f1a3b5c7"
down_revision: Union[str, None] = "e6b8d0f2a4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FK = "fk_liabilities_property_asset_id_assets"
_INDEX = "ix_liabilities_property_asset_id"


def _sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    # A plain ADD COLUMN, never a batch rebuild: rebuilding `liabilities` on
    # SQLite with foreign keys on cascades its commitment_links rows away
    # (#180's trap; the migration test caught it). SQLite takes the
    # reference inline, which alembic's add_column can't emit there.
    if _sqlite():
        op.execute(
            "ALTER TABLE liabilities ADD COLUMN property_asset_id CHAR(32) "
            f"CONSTRAINT {_FK} REFERENCES assets (id) ON DELETE SET NULL"
        )
    else:
        op.add_column("liabilities", sa.Column("property_asset_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(_FK, "liabilities", "assets", ["property_asset_id"], ["id"], ondelete="SET NULL")
    op.create_index(_INDEX, "liabilities", ["property_asset_id"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="liabilities")
    if not _sqlite():  # SQLite drops an inline reference with its column
        op.drop_constraint(_FK, "liabilities", type_="foreignkey")
    op.drop_column("liabilities", "property_asset_id")
