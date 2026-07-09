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


class RegisterResponse(UserResponse):
    """Registration result: the user plus their one-time recovery code.

    The recovery code is shown exactly once — it is never stored in a
    recoverable form, only used to wrap the user's data-encryption key.
    """

    recovery_code: str


class ForgotPasswordRequest(BaseModel):
    """Request a password reset email."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Set a new password using an emailed reset token.

    Without the recovery code the user's data-encryption key cannot be
    recovered: a new one is issued and existing bank data is purged (it can be
    rebuilt by re-syncing from the bank).
    """

    token: str
    new_password: str = Field(min_length=8, max_length=128)
    recovery_code: str | None = None


class ChangePasswordRequest(BaseModel):
    """Change password while logged in (rewraps the DEK — no data loss)."""

    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    """Confirm account deletion with the current password."""

    password: str


# --- Asset Schemas ---


class AssetValuationCreate(BaseModel):
    """Record an asset's value as of a date (defaults to today)."""

    value: Decimal
    valued_at: date | None = None


class AssetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    asset_type: str = Field(default="other", pattern="^(isa|savings|investment|pension|property|crypto|other|mortgage|loan|other_liability)$")
    value: Decimal
    valued_at: date | None = None
    # Projection assumption (%/yr, may be negative). Null → projection default.
    assumed_growth_pct: Decimal | None = Field(default=None, ge=-50, le=50)
    # Planned monthly saving into this asset (paydown when it's a liability).
    monthly_contribution: Decimal | None = Field(default=None, ge=0)


class AssetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    asset_type: str | None = Field(
        default=None, pattern="^(isa|savings|investment|pension|property|crypto|other|mortgage|loan|other_liability)$"
    )
    assumed_growth_pct: Decimal | None = Field(default=None, ge=-50, le=50)
    monthly_contribution: Decimal | None = Field(default=None, ge=0)


class AssetValuationResponse(BaseModel):
    id: uuid.UUID
    value: Decimal
    valued_at: date

    model_config = ConfigDict(from_attributes=True)


class AssetResponse(BaseModel):
    id: uuid.UUID
    name: str
    asset_type: str
    assumed_growth_pct: Decimal | None = None
    monthly_contribution: Decimal | None = None
    valuations: list[AssetValuationResponse] = []

    model_config = ConfigDict(from_attributes=True)


class NetWorthPoint(BaseModel):
    date: date
    bank: Decimal
    assets: Decimal
    net_worth: Decimal


class AssetFlowCreate(BaseModel):
    """Record money added to (+) or withdrawn from (−) an asset."""

    amount: Decimal
    flow_date: date | None = None


class AssetFlowResponse(BaseModel):
    id: uuid.UUID
    amount: Decimal
    flow_date: date

    model_config = ConfigDict(from_attributes=True)


class AssetDecomposition(BaseModel):
    """Contribution-vs-growth split of manual-asset movement over a window."""

    start_date: date
    end_date: date
    assets_start: Decimal
    assets_end: Decimal
    assets_delta: Decimal
    contributions: Decimal
    growth: Decimal
    flows_recorded: int


class NudgeResponse(BaseModel):
    """An honest, dismissible observation: a fact + its arithmetic and source."""

    id: str
    rank: int
    body: str
    detail: str
    source: str
    as_of: date | None


class ProjectionPoint(BaseModel):
    date: date
    value: Decimal
    # Component breakdown: cash buffer (drained first in negative months),
    # the swept-surplus bucket, and manual assets.
    cash: Decimal | None = None
    invested: Decimal | None = None
    assets: Decimal | None = None


class AssetAssumption(BaseModel):
    name: str
    growth_pct: Decimal
    monthly_contribution: Decimal = Decimal(0)


class ContributionBasis(BaseModel):
    """The cashflow arithmetic behind a derived contribution."""

    income_monthly: Decimal
    bills_monthly: Decimal
    avg_spending_monthly: Decimal
    contribution: Decimal
    spending_months_sampled: int
    # False = the "all my future cashflow into my wealth" scenario: the
    # measured average is shown but NOT subtracted from the surplus.
    spending_subtracted: bool = True


class ProjectionResponse(BaseModel):
    """A net-worth projection from stated assumptions — an estimate, not advice."""

    current_net_worth: Decimal
    target_amount: Decimal | None
    target_date: date | None
    monthly_contribution: Decimal
    contribution_basis: ContributionBasis | None = None
    annual_growth_pct: Decimal
    # 'cashflow': the surplus series comes from the same engine as the
    # Cashflow forecast; 'custom': a flat user-typed amount.
    mode: str = "custom"
    bank_component: Decimal = Decimal(0)
    asset_assumptions: list[AssetAssumption] = []
    as_of: date
    timeline: list[ProjectionPoint]


# --- Categorization Rule Schemas ---


class RuleCreate(BaseModel):
    """Create a categorization rule."""

    pattern: str = Field(min_length=1, max_length=200)
    match_type: str = Field(default="contains", pattern="^(exact|contains|regex)$")
    match_field: str = Field(default="any", pattern="^(any|merchant|description)$")
    category: str = Field(min_length=1, max_length=100)
    pack_id: uuid.UUID | None = None


class RuleUpdate(BaseModel):
    """Update a categorization rule."""

    pattern: str | None = Field(default=None, min_length=1, max_length=200)
    match_type: str | None = Field(default=None, pattern="^(exact|contains|regex)$")
    match_field: str | None = Field(default=None, pattern="^(any|merchant|description)$")
    category: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None


class RuleResponse(BaseModel):
    id: uuid.UUID
    pack_id: uuid.UUID | None
    pattern: str
    match_type: str
    match_field: str
    category: str
    source: str
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class RulePackCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class RulePackUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


class RulePackResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    share_code: str | None
    imported_from: str | None
    enabled: bool
    rules: list[RuleResponse] = []

    model_config = ConfigDict(from_attributes=True)


class RulePreviewRequest(BaseModel):
    """Dry-run a rule against the user's transactions."""

    pattern: str = Field(min_length=1, max_length=200)
    match_type: str = Field(default="contains", pattern="^(exact|contains|regex)$")
    match_field: str = Field(default="any", pattern="^(any|merchant|description)$")


class RuleImportRequest(BaseModel):
    share_code: str = Field(min_length=1, max_length=20)


# --- Auth Schemas ---


class Token(BaseModel):
    """JWT token response.

    `recovery_code` is only present when logging in provisioned a fresh
    data-encryption key for an account that predates per-user encryption —
    the UI must show it once and require acknowledgement.
    """

    access_token: str
    token_type: str = "bearer"
    recovery_code: str | None = None


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
    # Computed: matches a confirmed commitment (rent, salary, subscriptions…),
    # so the UI can separate bills from discretionary spending.
    is_commitment: bool = False
    # Computed: converted to a payment plan ("paid on finance") — the UI badges
    # it and spending excludes it (counted via its installments instead).
    is_financed: bool = False
    # Computed: why the transaction is hidden from spending by default —
    # 'internal_transfer' (a matched debit/credit pair between own accounts) or
    # 'card_payment' (settling a credit card, not new spending). Null = counts.
    # Uses the same detection as the spending aggregates so the list and the
    # totals can never disagree.
    excluded_reason: str | None = None
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


class TransactionFacetsResponse(BaseModel):
    """Distinct values for the transaction-list filter dropdowns."""

    categories: list[str]
    merchants: list[str]


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
    repayment_strategy: str | None = None  # full_balance | fixed | installments | scheduled
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
    repayment_fixed_amount: Decimal | None = None
    repayment_installments: int | None = None
    pay_from_account_id: str | None = None


class CashflowSummary(BaseModel):
    available_cash: Decimal
    overdraft_cushion: Decimal
    credit_owed: Decimal
    savings_total: Decimal = Decimal(0)
    assets_total: Decimal = Decimal(0)
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
    match_key: str | None = None
    is_payday: bool = False

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
    # Optional merchant/description text to match transactions against, so a
    # manually-added commitment (e.g. "Rent") actually excludes its real
    # transactions even when their description differs from the label.
    match_merchant: str | None = None


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
    # See CommitmentCreate.match_merchant. Empty string clears the match key.
    match_merchant: str | None = None
    # "This is my payday" — only meaningful on income; the payday calc ignores
    # the flag on expenses.
    is_payday: bool | None = None


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


class MoneyOutComposition(BaseModel):
    """What makes up the money-out figure — so exclusions are named, not hidden."""

    card_repayments: Decimal
    transfers: Decimal
    commitments: Decimal
    other: Decimal


class SpendingResponse(BaseModel):
    # 'money_out' (default): cash that actually left your bank accounts,
    # reconciles to a statement. 'purchases': spend booked at purchase time.
    lens: str = "money_out"
    period: str
    period_start: date
    period_end: date
    total_spent: Decimal
    # Purchases-lens split (0 under the money-out lens).
    charged_to_credit: Decimal
    paid_from_cash: Decimal
    # Money-out-lens breakdown (null under the purchases lens).
    composition: MoneyOutComposition | None = None
    by_category: list[CategorySlice]
    top_merchants: list[MerchantSlice]


class SpendingTransaction(BaseModel):
    """One transaction behind a spending figure (drill-down)."""

    id: str
    date: date
    description: str
    merchant: str | None
    amount: Decimal
    category: str
    account: str
    kind: str  # cash | credit


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
    source_transaction_id: uuid.UUID | None = None
    active: bool

    model_config = ConfigDict(from_attributes=True)


class PlanFromTransaction(BaseModel):
    """Convert a purchase into a payment plan: pay `monthly_amount` for `months`."""

    transaction_id: uuid.UUID
    months: int = Field(ge=1, le=120)
    monthly_amount: Decimal = Field(gt=0)
    start_date: date


class RepaymentScheduleItemCreate(BaseModel):
    """A single scheduled credit-card repayment (for the `scheduled` strategy)."""

    due_date: date
    amount: Decimal = Field(gt=0)


class RepaymentScheduleItemResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    due_date: date
    amount: Decimal

    model_config = ConfigDict(from_attributes=True)
