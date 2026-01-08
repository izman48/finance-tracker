"""Initial schema - users, accounts, transactions

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('truelayer_access_token', sa.Text(), nullable=True),
        sa.Column('truelayer_refresh_token', sa.Text(), nullable=True),
        sa.Column('truelayer_token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # Create accounts table
    op.create_table(
        'accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('provider_name', sa.String(255), nullable=False),
        sa.Column('account_type', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='GBP'),
        sa.Column('current_balance', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('available_balance', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('balance_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_accounts_user_id', 'accounts', ['user_id'])
    op.create_index('ix_accounts_external_id', 'accounts', ['external_id'], unique=True)

    # Create transactions table
    op.create_table(
        'transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('external_id', sa.String(255), nullable=False),
        sa.Column('transaction_type', sa.String(10), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(3), nullable=False, server_default='GBP'),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('merchant_name', sa.String(255), nullable=True),
        sa.Column('category', sa.String(100), nullable=True),
        sa.Column('subcategory', sa.String(100), nullable=True),
        sa.Column('is_recurring', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('recurring_group_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('transaction_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_transactions_account_id', 'transactions', ['account_id'])
    op.create_index('ix_transactions_external_id', 'transactions', ['external_id'], unique=True)
    op.create_index('ix_transactions_category', 'transactions', ['category'])
    op.create_index('ix_transactions_is_recurring', 'transactions', ['is_recurring'])
    op.create_index('ix_transactions_recurring_group_id', 'transactions', ['recurring_group_id'])
    op.create_index('ix_transactions_transaction_date', 'transactions', ['transaction_date'])
    op.create_index('ix_transactions_account_date', 'transactions', ['account_id', 'transaction_date'])
    op.create_index('ix_transactions_category_date', 'transactions', ['category', 'transaction_date'])


def downgrade() -> None:
    op.drop_table('transactions')
    op.drop_table('accounts')
    op.drop_table('users')
