import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.account import AccountType
from app.models.transaction import TransactionType


# --- User Schemas ---


class UserCreate(BaseModel):
    """Schema for creating a user."""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Schema for user in API responses."""

    id: uuid.UUID
    email: str
    created_at: datetime
    has_bank_connection: bool = False

    model_config = ConfigDict(from_attributes=True)


# --- Auth Schemas ---


class Token(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Data extracted from JWT token."""

    user_id: uuid.UUID | None = None


# --- Account Schemas ---


class AccountResponse(BaseModel):
    """Schema for account in API responses."""

    id: uuid.UUID
    provider_name: str
    account_type: AccountType
    display_name: str
    currency: str
    current_balance: float | None
    available_balance: float | None
    balance_updated_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


# --- Transaction Schemas ---


class TransactionResponse(BaseModel):
    """Schema for transaction in API responses."""

    id: uuid.UUID
    account_id: uuid.UUID
    transaction_type: TransactionType
    amount: float
    currency: str
    description: str
    merchant_name: str | None
    category: str | None
    subcategory: str | None
    is_recurring: bool
    transaction_date: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionUpdate(BaseModel):
    """Schema for updating transaction fields."""

    category: str | None = None
    subcategory: str | None = None


class TransactionListResponse(BaseModel):
    """Paginated list of transactions."""

    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int


# --- Insight Schemas ---


class SpendingByCategory(BaseModel):
    """Spending breakdown by category."""

    category: str
    total_amount: Decimal
    transaction_count: int
    percentage: float


class RecurringPayment(BaseModel):
    """Detected recurring payment."""

    merchant_name: str
    average_amount: Decimal
    frequency: str  # "weekly", "monthly", "yearly"
    total_spent: Decimal
    transaction_count: int


class OpportunityCost(BaseModel):
    """Opportunity cost calculation."""

    original_amount: Decimal
    potential_value: Decimal
    growth_amount: Decimal
    growth_percentage: float
    investment_type: str  # e.g., "S&P 500"
    time_period_years: int


# --- Banking Schemas ---


class BankConnectionURL(BaseModel):
    """Bank connection authorization URL."""

    auth_url: str
    message: str = "Visit this URL to connect your bank account"


class BankConnectionCallback(BaseModel):
    """Bank connection OAuth callback data."""

    code: str
    state: str


class SyncAccountsResponse(BaseModel):
    """Response from syncing accounts."""

    accounts_synced: int
    accounts: list[AccountResponse]
    message: str


class SyncTransactionsRequest(BaseModel):
    """Request to sync transactions."""

    days: int = 90


class SyncTransactionsResponse(BaseModel):
    """Response from syncing transactions."""

    transactions_synced: int
    message: str
