"""Per-user encryption: DEK wrap columns on users; encrypted data columns

Sensitive columns (transaction description/merchant/amount, account details,
bank tokens) are now encrypted with a per-user data-encryption key that the
server only holds during an active session (see core/user_crypto.py). Numeric
and sized-string columns become Text to hold Fernet ciphertext.

Existing rows were written before any user had a DEK, so they can never be
decrypted — they are removed (same rationale as a1b2c3d4e5f6: bank data is
re-fetchable by reconnecting/re-syncing). Users keep their logins; each gets a
DEK provisioned at next login and a one-time recovery code.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Wrapped-DEK storage. Nullable: provisioned lazily at next login.
    op.add_column("users", sa.Column("wrapped_dek", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("dek_salt", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("recovery_wrapped_dek", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("recovery_salt", sa.String(64), nullable=True))

    # Pre-DEK rows are unreadable under the new scheme; remove them before the
    # type changes. Cascades clear accounts and transactions.
    op.execute("DELETE FROM bank_connections")

    # Ciphertext columns: everything becomes Text.
    op.alter_column("transactions", "amount", type_=sa.Text(), postgresql_using="amount::text")
    op.alter_column("transactions", "merchant_name", type_=sa.Text())
    # transactions.description is already Text.
    op.alter_column("accounts", "provider_name", type_=sa.Text())
    op.alter_column("accounts", "display_name", type_=sa.Text())
    op.alter_column(
        "accounts", "current_balance", type_=sa.Text(), postgresql_using="current_balance::text"
    )
    op.alter_column(
        "accounts", "available_balance", type_=sa.Text(), postgresql_using="available_balance::text"
    )
    # bank_connections provider/token columns are already unsized VARCHAR/Text.


def downgrade() -> None:
    op.execute("DELETE FROM bank_connections")
    op.alter_column(
        "accounts", "available_balance", type_=sa.Numeric(12, 2),
        postgresql_using="available_balance::numeric",
    )
    op.alter_column(
        "accounts", "current_balance", type_=sa.Numeric(12, 2),
        postgresql_using="current_balance::numeric",
    )
    op.alter_column("accounts", "display_name", type_=sa.String(255))
    op.alter_column("accounts", "provider_name", type_=sa.String(255))
    op.alter_column("transactions", "merchant_name", type_=sa.String(255))
    op.alter_column(
        "transactions", "amount", type_=sa.Numeric(12, 2), postgresql_using="amount::numeric"
    )
    op.drop_column("users", "recovery_salt")
    op.drop_column("users", "recovery_wrapped_dek")
    op.drop_column("users", "dek_salt")
    op.drop_column("users", "wrapped_dek")
