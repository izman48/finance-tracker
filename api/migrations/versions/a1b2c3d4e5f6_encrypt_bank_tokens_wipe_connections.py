"""Encrypt bank tokens at rest: wipe existing plaintext connections

Bank OAuth tokens are now stored encrypted (Fernet) via the EncryptedString
column type. Existing rows hold plaintext tokens that cannot be decrypted with
the cipher, so we remove them here. Tokens are short-lived and re-fetchable:
users simply reconnect their bank, which writes encrypted values going forward.
Deleting bank_connections cascades to accounts and transactions.

Revision ID: a1b2c3d4e5f6
Revises: 9ab2b0b9d566
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9ab2b0b9d566"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove plaintext token rows; cascade clears dependent accounts/transactions.
    op.execute("DELETE FROM bank_connections")


def downgrade() -> None:
    # Data-only migration; nothing to restore (tokens are re-fetched on reconnect).
    pass
