import type { CardStatementSummary } from './lib/cardStatement'
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
  // The reclassification in effect; null = automatic detection. locked=true
  // means hand-set (rules never touch it), false means a rule applied it.
  counts_as_override?: 'spending' | 'transfer' | 'card_payment' | null
  counts_as_locked?: boolean
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
  // Credit accounts only: money owed, positive on every provider (negative =
  // in credit). current_balance is raw, and its sign differs by provider.
  credit_owed: number | string | null
  overdraft_limit: number | null
  repayment_cadence: string | null
  repayment_day: number | null
  repayment_interval_months: number | null
  repayment_anchor_date: string | null
  repayment_strategy: string | null
  repayment_fixed_amount: number | null
  repayment_installments: number | null
  pay_from_account_id: string | null
  instalment_card?: boolean
  // A standard card still on `scheduled`: show a "fix this" notice (T-10-6).
  repayment_fix_needed?: boolean
  // Credit accounts (T-10-14a): the current statement, null when none is
  // entered; absent when the response carries no statement data.
  statement?: CardStatementSummary | null
}

export interface CashflowSummary {
  available_cash: number
  overdraft_cushion: number
  credit_owed: number
  // Owed on liabilities (loans, finance, BNPL), subtracted in net_worth (T-10-7b).
  liabilities_total?: number | string
  // Value today of ISAs, investment accounts, pensions and crypto (T-11-7).
  investments_total?: number | string
  // Card balances owed plus liabilities_total, summed by the server (T-10-14a).
  total_owed?: number | string | null
  net_worth: number
  committed_before_payday: number
  safe_to_spend: number
  savable: number
  // Income Claude added that savable leaves out until it is kept (T-08-20).
  savable_pending_keep_total?: number | string
  // Bills Claude removed or reduced that safe to spend still counts until kept (T-08-21b).
  safe_to_spend_pending_keep_total?: number | string
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
  // Claude's latest change still in effect (links to /changes#change-{audit_id}).
  changed_by_claude?: ClaudeMarker | null
  // Income whose latest payment hasn't arrived (T-08-10): shown, never counted.
  late?: boolean
  expected_date?: string | null
  // Income Claude raised or confirmed: not counted in savable until kept (T-08-20).
  keep?: 'pending' | 'kept' | null
  // Carries a loan's repayment / an investment's contribution: edit it there (T-10-8, T-11-3).
  linked_liability?: boolean
  linked_holding?: boolean
  kept_at?: string | null
  // The audit rows the Keep button keeps, oldest first.
  keep_audit_ids?: string[]
  // What a pending keep holds: savable ("income") or safe to spend ("expense_cut").
  keep_kind?: 'income' | 'expense_cut' | null
  // The before-Claude values the figures still use, while held (KP18).
  held_amount?: number | string | null
  held_next_date?: string | null
}

export interface ClaudeMarker {
  audit_id: string
  at: string
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
  cadence: string | null
  interval_days: number | null
  interval_months: number | null
  end_date: string | null
  apr: number | null
  fee_amount: number | null
  active: boolean
  changed_by_claude?: ClaudeMarker | null
  // Set once the real transaction that paid it has landed (T-08-7).
  matched_transaction_id?: string | null
  // Expected income past its date + 7 days with no matching credit (T-08-7).
  late?: boolean
  // An unpaid planned expense past its date; decided by the API, still counted.
  overdue?: boolean
}
