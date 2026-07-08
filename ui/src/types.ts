/** Shared API entity types — one declaration per entity.
 *  (Decimal fields arrive as strings from the API; coerce with Number(...)
 *  before arithmetic. Central coercion mappers come with the Phase 3 backend
 *  work — see REDESIGN_PLAN.md.)
 */

export interface Transaction {
  id: string
  account_id: string
  transaction_type: string
  amount: number
  currency: string
  description: string
  merchant_name: string | null
  category: string | null
  subcategory: string | null
  is_recurring: boolean
  is_commitment: boolean
  is_financed: boolean
  // Why this is hidden from spending by default — same detection as the
  // aggregates, so figures and list always reconcile.
  excluded_reason: 'internal_transfer' | 'card_payment' | null
  transaction_date: string
}

export interface Account {
  id: string
  display_name: string
  provider_name: string
  account_type: string
}

export interface BankConnection {
  id: string
  provider_name: string
  is_expired: boolean
  expires_at: string | null
}

export interface BankStatus {
  is_connected: boolean
  connections_count: number
  last_synced_at: string | null
  connections: BankConnection[]
  message: string
}

export interface NextRepayment {
  account_id: string
  label: string
  amount: number
  due_date: string
}

export interface SummaryAccount {
  id: string
  display_name: string
  provider_name: string
  account_type: string
  role: string
  current_balance: number | null
  overdraft_limit: number | null
  repayment_cadence: string | null
  repayment_day: number | null
  repayment_interval_months: number | null
  repayment_anchor_date: string | null
  repayment_strategy: string | null
  repayment_fixed_amount: number | null
  repayment_installments: number | null
  pay_from_account_id: string | null
}

export interface CashflowSummary {
  available_cash: number
  overdraft_cushion: number
  credit_owed: number
  net_worth: number
  committed_before_payday: number
  safe_to_spend: number
  savable: number
  next_payday: string | null
  next_repayments: NextRepayment[]
  accounts: SummaryAccount[]
}

export interface Commitment {
  id: string
  direction: 'income' | 'expense'
  label: string
  amount: number
  cadence: string
  interval_days: number | null
  interval_months: number | null
  next_date: string
  source: 'detected' | 'manual'
  status: 'suggested' | 'confirmed' | 'dismissed'
  account_id: string | null
  match_key: string | null
  is_payday?: boolean
}

export interface PlannedItem {
  id: string
  name: string
  direction: string
  kind: string
  start_date: string
  amount: number | null
  total_amount: number | null
  installments: number | null
}
