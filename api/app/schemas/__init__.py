import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.account import AccountType
from app.models.transaction import TransactionType


# --- User Schemas ---


class UserCreate(BaseModel):
    """Schema for creating a user."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    """Schema for user in API responses."""

    id: uuid.UUID
    email: str
    created_at: datetime
    has_bank_connection: bool = False

    model_config = ConfigDict(from_attributes=True)


class ForgotPasswordRequest(BaseModel):
    """Request a password reset email."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Set a new password using an emailed reset token."""

    token: str
    new_password: str = Field(min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    """Confirm account deletion with the current password."""

    password: str


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


# --- Analytics / Cashflow Schemas ---


class AccountSettingUpdate(BaseModel):
    """Patch an account's cashflow settings (all optional)."""

    role: str | None = None  # spending | savings | credit | excluded
    overdraft_limit: Decimal | None = None
    repayment_cadence: str | None = None  # monthly | end_of_month | every_n_months | weekly
    repayment_interval_months: int | None = None
    repayment_day: int | None = Field(default=None, ge=1, le=31)
    repayment_anchor_date: date | None = None
    repayment_strategy: str | None = None  # full_balance | fixed | installments
    repayment_fixed_amount: Decimal | None = None
    repayment_installments: int | None = Field(default=None, ge=1, le=120)
    pay_from_account_id: uuid.UUID | None = None


class NextRepayment(BaseModel):
    account_id: str
    label: str
    amount: Decimal
    due_date: date


class CashflowAccount(BaseModel):
    id: str
    display_name: str
    provider_name: str
    account_type: str
    role: str
    current_balance: Decimal | None
    overdraft_limit: Decimal | None
    repayment_cadence: str | None = None
    repayment_day: int | None = None
    repayment_interval_months: int | None = None
    repayment_anchor_date: date | None = None
    repayment_strategy: str | None = None
    repayment_installments: int | None = None
    pay_from_account_id: str | None = None


class CashflowSummary(BaseModel):
    available_cash: Decimal
    overdraft_cushion: Decimal
    credit_owed: Decimal
    net_worth: Decimal
    committed_before_payday: Decimal
    safe_to_spend: Decimal
    savable: Decimal
    next_payday: date | None
    next_repayments: list[NextRepayment]
    accounts: list[CashflowAccount]


class CommitmentResponse(BaseModel):
    id: uuid.UUID
    direction: str
    label: str
    amount: Decimal
    cadence: str
    interval_days: int | None
    interval_months: int | None
    next_date: date
    source: str
    status: str
    account_id: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class CommitmentFromTransaction(BaseModel):
    """Mark an existing transaction as recurring."""

    transaction_id: uuid.UUID
    cadence: str = "monthly"  # weekly | monthly | every_n_months


class CommitmentCreate(BaseModel):
    """Manually add a commitment."""

    direction: str  # income | expense
    label: str
    amount: Decimal
    cadence: str = "monthly"
    interval_days: int | None = None
    interval_months: int | None = None
    next_date: date
    account_id: uuid.UUID | None = None


class CommitmentUpdate(BaseModel):
    """Confirm/dismiss or edit a commitment (all optional)."""

    status: str | None = None  # suggested | confirmed | dismissed
    label: str | None = None
    amount: Decimal | None = None
    cadence: str | None = None
    interval_days: int | None = None
    interval_months: int | None = None
    next_date: date | None = None
    account_id: uuid.UUID | None = None


class ForecastEvent(BaseModel):
    label: str
    amount: Decimal  # signed: income +, expense/repayment −
    kind: str        # income | expense | repayment


class ForecastPoint(BaseModel):
    date: date
    balance: Decimal
    events: list[ForecastEvent]


class ForecastResponse(BaseModel):
    horizon: str
    horizon_end: date
    start_balance: Decimal
    end_balance: Decimal
    min_balance: Decimal
    min_date: date
    overdraft_limit: Decimal
    breaches: list[str]
    timeline: list[ForecastPoint]


class CategorySlice(BaseModel):
    category: str
    total: Decimal
    count: int


class MerchantSlice(BaseModel):
    merchant: str
    total: Decimal


class SpendingResponse(BaseModel):
    period: str
    period_start: date
    period_end: date
    total_spent: Decimal
    charged_to_credit: Decimal
    paid_from_cash: Decimal
    by_category: list[CategorySlice]
    top_merchants: list[MerchantSlice]


class MonthSpend(BaseModel):
    month: str  # "YYYY-MM"
    total: Decimal
    charged_to_credit: Decimal
    paid_from_cash: Decimal


class SpendingTrendResponse(BaseModel):
    months: list[MonthSpend]


class PlannedItemCreate(BaseModel):
    name: str
    direction: str = "expense"
    kind: str  # one_off | recurring | installment_plan
    start_date: date
    amount: Decimal | None = None
    cadence: str | None = None
    interval_days: int | None = None
    interval_months: int | None = None
    end_date: date | None = None
    total_amount: Decimal | None = None
    installments: int | None = Field(default=None, ge=1, le=120)
    apr: Decimal | None = None
    fee_amount: Decimal | None = None
    account_id: uuid.UUID | None = None


class PlannedItemResponse(BaseModel):
    id: uuid.UUID
    name: str
    direction: str
    kind: str
    start_date: date
    amount: Decimal | None
    cadence: str | None
    interval_days: int | None
    interval_months: int | None
    end_date: date | None
    total_amount: Decimal | None
    installments: int | None
    apr: Decimal | None
    fee_amount: Decimal | None
    account_id: uuid.UUID | None
    active: bool

    model_config = ConfigDict(from_attributes=True)
