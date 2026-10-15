import type { RepaymentWarning } from '../lib/repaymentWarnings'
import axios from 'axios'
import { isAnonymized } from '../lib/anonymize'
import { sampleResponse } from '../lib/sampleAccount'
import type { AuditItem, AuditPage } from '../lib/changes'
import type { BudgetEntry, BudgetsResponse, SuggestResponse } from '../lib/budgets'
import type { InvestmentGraph } from '../lib/investments'
import type { HistoryResponse } from '../lib/budgetHistory'

// Unset -> local dev default; empty string -> same-origin (production behind Caddy)
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth token, and — while anonymized — serve the fixed sample account
// instead of the real API (reads) and block writes.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  if (isAnonymized()) {
    const method = (config.method ?? 'get').toLowerCase()
    const url = config.url ?? ''
    const isAuth = url.includes('/auth/login') || url.includes('/auth/register')
    if (method !== 'get' && !isAuth) {
      // Editing real data while looking at sample values invites mistakes —
      // block the write and let a listener surface a toast.
      if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('anonymize:blocked'))
      return Promise.reject(new axios.Cancel('anonymized-write-blocked'))
    }
    if (!isAuth) {
      // Short-circuit the network: return sample data from a local adapter, so
      // the real API is never even contacted while anonymized.
      config.adapter = async (cfg) => ({
        data: sampleResponse(cfg.url ?? '', cfg.params),
        status: 200,
        statusText: 'OK',
        headers: {},
        config: cfg,
      })
    }
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Auth endpoints
export const authApi = {
  // Returns the one-time recovery code — shown once, never retrievable again.
  register: (email: string, password: string) =>
    api.post<{ id: string; email: string; recovery_code: string }>('/auth/register', {
      email,
      password,
    }),

  // recovery_code is set only when login provisioned encryption for an
  // account that predates it — show it like the signup one.
  login: (email: string, password: string) =>
    api.post<{ access_token: string; token_type: string; recovery_code: string | null }>(
      '/auth/login',
      new URLSearchParams({ username: email, password }),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    ),

  me: () => api.get('/auth/me'),

  changePassword: (currentPassword: string, newPassword: string) =>
    api.post<{ access_token: string; token_type: string }>('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),

  forgotPassword: (email: string) =>
    api.post('/auth/forgot-password', { email }),

  // Without the recovery code, resetting issues a new encryption key:
  // everything encrypted under the old one is purged (`message` lists it)
  // and a fresh code comes back.
  resetPassword: (token: string, newPassword: string, recoveryCode?: string) =>
    api.post<{ message: string; recovery_code?: string }>('/auth/reset-password', {
      token,
      new_password: newPassword,
      recovery_code: recoveryCode || undefined,
    }),

  deleteAccount: (password: string) =>
    api.post('/auth/delete-account', { password }),
}

// OAuth consent for remote MCP clients. `params` is the authorization request
// exactly as the client put it in the URL; the API validates it.
export interface OAuthRequestDetails {
  client_name: string
  redirect_host: string
  requested_scopes: string[]
}

export const oauthApi = {
  details: (params: Record<string, string>) =>
    api.get<OAuthRequestDetails>('/oauth/authorize/details', { params }),

  decide: (params: Record<string, string>, approve: boolean, scopes: string[]) =>
    api.post<{ redirect_to: string }>('/oauth/authorize', { ...params, approve, scopes }),
}

// Categorization rules & packs
export interface Rule {
  id: string
  pack_id: string | null
  pattern: string
  match_type: string
  match_field: string
  category: string
  // Optional: matching transactions also count as this in spending figures.
  counts_as: string | null
  source: string
  enabled: boolean
}

export interface RulePack {
  id: string
  name: string
  description: string | null
  share_code: string | null
  imported_from: string | null
  enabled: boolean
  rules: Rule[]
}

export const rulesAPI = {
  list: () => api.get<{ packs: RulePack[]; personal: Rule[] }>('/rules'),
  create: (data: { pattern: string; match_type: string; match_field: string; category: string; counts_as?: string | null; pack_id?: string | null }) =>
    api.post('/rules', data),
  update: (id: string, data: Partial<Pick<Rule, 'pattern' | 'match_type' | 'match_field' | 'category' | 'enabled'>>) =>
    api.patch(`/rules/${id}`, data),
  remove: (id: string) => api.delete(`/rules/${id}`),
  preview: (data: { pattern: string; match_type: string; match_field: string }) =>
    api.post('/rules/preview', data),
  applyNow: () => api.post('/rules/apply'),
  createPack: (data: { name: string; description?: string }) => api.post('/rules/packs', data),
  updatePack: (id: string, data: { name?: string; description?: string; enabled?: boolean }) =>
    api.patch(`/rules/packs/${id}`, data),
  removePack: (id: string) => api.delete(`/rules/packs/${id}`),
  sharePack: (id: string) => api.post<{ share_code: string; share_url: string }>(`/rules/packs/${id}/share`),
  unsharePack: (id: string) => api.delete(`/rules/packs/${id}/share`),
  previewShared: (code: string) => api.get(`/rules/shared/${code}`),
  importPack: (shareCode: string) => api.post('/rules/import', { share_code: shareCode }),
}

// Manual assets & net worth
export interface AssetValuation {
  id: string
  value: string
  valued_at: string
}

export interface Asset {
  id: string
  name: string
  asset_type: string
  // Projection assumption (%/yr, may be negative); null → projection default.
  assumed_growth_pct: string | null
  // Planned monthly saving into this asset (paydown on a liability).
  monthly_contribution: string | null
  valuations: AssetValuation[]
  /** Value today from the holding engine (a linked contribution paid since
   *  the last valuation included); null before a first value (#210). */
  value_today?: string | null
  /** A property with a mortgage (T-12-6b): what its mortgages owe today and
   *  value today minus that, both the API's; null otherwise. Display only. */
  mortgage_owed?: string | null
  equity?: string | null
  // The bill that carries its contribution while linked (T-11-3c).
  linked_commitment?: {
    id: string; label: string; amount?: string; next_date?: string; pay_from_account_id?: string | null
    /** The link made this bill (opting out deletes it); false: the user's own bill, which stays. */
    created?: boolean
  } | null
}

/** PUT /assets/{id}/contribution: the user's terms and choice only (#210). */
export interface ContributionBody {
  amount: string
  next_date: string
  pay_from_account_id?: string
  commitment_choice?: string
}

export interface NetWorthPoint {
  date: string
  bank: string
  assets: string
  // Owed on liabilities (loans, finance, BNPL); net_worth = bank + assets − liabilities.
  liabilities?: string
  net_worth: string
  // The graph groups (T-11-6): net_worth = cash + property − debt, plus
  // investments unless include_investments=false (then still given, "Not included").
  cash?: string
  investments?: string
  property?: string
  debt?: string
}

export interface NetWorthChange {
  key: '1m' | '3m' | '6m' | '1y' | 'all'
  label: string
  from_date: string | null
  // False when the horizon reaches back before any data we hold.
  available: boolean
  from_value: string | null
  change: string | null
  // Percent of the starting value; null when that start was ≤ 0.
  change_pct: string | null
}

export interface NetWorthPosition {
  as_of: string
  net_worth: string
  bank: string
  assets: string
  liabilities?: string
  // First date any wealth data reaches back to.
  since: string | null
  changes: NetWorthChange[]
}

export interface AssetDecomposition {
  start_date: string
  end_date: string
  assets_start: string
  assets_end: string
  assets_delta: string
  contributions: string
  growth: string
  flows_recorded: number
}

export interface ProjectionPoint {
  date: string
  value: string
  cash?: string
  invested?: string
  assets?: string
}

export interface AssetAssumption {
  name: string
  growth_pct: string
  monthly_contribution: string
}

export interface ContributionBasis {
  income_monthly: string
  bills_monthly: string
  avg_spending_monthly: string
  contribution: string
  spending_months_sampled: number
  // False = "all my future cashflow into my wealth": the measured average is
  // shown but was not subtracted from the surplus.
  spending_subtracted: boolean
  // What was actually subtracted and where it came from ('measured'|'custom').
  spending_applied: string
  spending_source: string
  // T-10-15b, when the request sent spending_source: what was asked for,
  // what was used, the active budget total a month, and whether budgets fell
  // back to the average (no active budgets).
  spending_choice?: 'budgets' | 'average' | null
  spending_used?: 'budgets' | 'average' | 'estimate' | null
  /** Holdings' unlinked monthly contributions moved from cash (T-12-0). */
  contributions_monthly?: string
  budgets_monthly?: string | null
  budgets_fallback?: boolean
  // The evidence: each sampled month's measured spending (YYYY-MM).
  sampled_months: { month: string; total: string }[]
}

export interface Projection {
  current_net_worth: string
  target_amount: string | null
  target_date: string | null
  monthly_contribution: string
  // Present when the contribution was derived from the user's cashflow.
  contribution_basis: ContributionBasis | null
  annual_growth_pct: string
  // 'cashflow' (surplus series from the forecast engine) or 'custom'.
  mode: string
  bank_component: string
  asset_assumptions: AssetAssumption[]
  as_of: string
  timeline: ProjectionPoint[]
}

/** A loan, retail finance or BNPL the user entered (T-10-7a/8). Money is a
 *  decimal string; every derived figure comes from the API. */
export interface Liability {
  id: string
  kind: 'loan' | 'finance' | 'bnpl' | 'mortgage'
  lender: string
  balance: string
  balance_as_of: string
  apr: string
  payment: string | null
  cadence: 'monthly' | 'four_weekly' | 'fortnightly' | 'weekly'
  start_date: string
  end_date: string | null
  opted_out: boolean
  /** A mortgage's property (T-12-6b), or null. */
  property_asset_id?: string | null
  current_balance: string
  next_payment_date: string | null
  payments_remaining: number | null
  payoff_date: string | null
  interest_remaining: string | null
  total_cost: string | null
  paid_off: boolean
  balance_stale: boolean
  linked_commitment: { id: string; label: string } | null
  link_result: 'created' | 'linked' | null
}

/** What the add/edit form sends: every term, money and APR as strings. */
export interface LiabilityBody {
  kind: Liability['kind']
  lender: string
  balance: string
  balance_as_of: string
  apr: string
  payment: string | null
  cadence: Liability['cadence']
  start_date: string
  end_date: string | null
  opted_out: boolean
  /** A mortgage's property (T-12-6b); null for none, and for every other kind. */
  property_asset_id?: string | null
  replaces_asset_id?: string
  commitment_choice?: string
}

/** One bill the repayment could be (409 `choose_commitment`, ux A7). */
export interface ChooseCandidate {
  id: string
  label: string
  amount: string
  cadence: string
  interval_days: number | null
  next_date: string
}

export const liabilitiesAPI = {
  list: () => api.get<Liability[]>('/liabilities'),
  create: (body: LiabilityBody) => api.post<Liability>('/liabilities', body),
  update: (id: string, body: LiabilityBody) => api.patch<Liability>(`/liabilities/${id}`, body),
  remove: (id: string) => api.delete(`/liabilities/${id}`),
}

// Investment graphs (T-11-4d): each investment and the total, from the
// holding engine. Web session; a holding id that isn't the caller's is 404.
export const holdingsAPI = {
  projection: (params: { months: number; holding_id?: string | null; annual_growth_pct?: number }) =>
    api.get<InvestmentGraph>('/holdings/projection', {
      params: { months: params.months, ...(params.holding_id ? { holding_id: params.holding_id } : {}),
        ...(params.annual_growth_pct != null ? { annual_growth_pct: params.annual_growth_pct } : {}) },
    }),
}

export const assetsAPI = {
  list: () => api.get<Asset[]>('/assets'),
  create: (data: { name: string; asset_type: string; value: number; valued_at?: string; assumed_growth_pct?: number | null; monthly_contribution?: number | null }) =>
    api.post('/assets', data),
  update: (id: string, data: { name?: string; asset_type?: string; assumed_growth_pct?: number | null; monthly_contribution?: number | null }) =>
    api.patch(`/assets/${id}`, data),
  remove: (id: string) => api.delete(`/assets/${id}`),
  addValuation: (id: string, data: { value: number; valued_at?: string }) =>
    api.post(`/assets/${id}/valuations`, data),
  /** Opt in to (or change) the monthly contribution as a linked bill (T-11-3c). */
  setContribution: (id: string, body: ContributionBody) => api.put(`/assets/${id}/contribution`, body),
  /** Opt out: the bill goes if the link created it (T-11-3c). */
  stopContribution: (id: string) => api.delete(`/assets/${id}/contribution`),
  removeValuation: (assetId: string, valuationId: string) =>
    api.delete(`/assets/${assetId}/valuations/${valuationId}`),
  // Record money added (+) / withdrawn (−) so growth can be told from saving.
  addFlow: (id: string, data: { amount: number; flow_date?: string }) =>
    api.post(`/assets/${id}/flows`, data),
  decomposition: (months = 12) =>
    api.get<AssetDecomposition>('/analytics/net-worth-decomposition', { params: { months } }),
  netWorthHistory: (months = 12, includeInvestments = true) =>
    api.get<NetWorthPoint[]>('/analytics/net-worth-history', {
      params: { months, ...(includeInvestments ? {} : { include_investments: 'false' }) },
    }),
  // Today's net worth and how far it has moved over 1m/3m/6m/1y/all-time.
  netWorthPosition: () => api.get<NetWorthPosition>('/analytics/net-worth-position'),
  // A projection from stated assumptions — an estimate, not advice.
  netWorthProjection: (params: {
    target_amount?: number
    monthly_contribution?: number
    annual_growth_pct?: number
    subtract_spending?: boolean
    monthly_spending?: number | string
    spending_source?: 'budgets' | 'average'
    include_investments?: 'false'
  }) => api.get<Projection>('/analytics/net-worth-projection', { params }),
}

// Health check
export const healthApi = {
  check: () => api.get('/health'),
}

// Server-side transaction filters. Filtering runs in Python after decryption
// (description/merchant/amounts are encrypted columns); `kind` mirrors the
// spending aggregates exactly so drilled figures always reconcile.
export interface TransactionQuery {
  page?: number
  page_size?: number
  account_id?: string
  search?: string
  category?: string[]
  merchant?: string
  type?: 'debit' | 'credit' | ''
  date_from?: string
  date_to?: string
  min_amount?: number | string
  max_amount?: number | string
  include_excluded?: boolean
  hide_transfers?: boolean
  hide_card_payments?: boolean
  exclude_commitments?: boolean
  kind?: 'spend' | 'cash' | 'credit' | 'money_out'
  sort?: 'date' | 'amount'
  sort_dir?: 'asc' | 'desc'
}

// FastAPI expects repeated keys for list params (category=a&category=b).
const listParams = (params: Record<string, unknown>) => {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => q.append(k, String(x)))
    else q.append(k, String(v))
  }
  return q
}

// Banking endpoints
// Budgets (T-09-2 / T-09-6). Web session; PUT upserts the listed categories, all or nothing.
export const budgetsAPI = {
  list: () => api.get<BudgetsResponse>('/budgets'),
  /** The list plus the categories a new budget may use (heavier: only when Add budget needs it). */
  listWithCategories: () => api.get<BudgetsResponse>('/budgets', { params: { include: 'categories' } }),
  suggest: () => api.post<SuggestResponse>('/budgets/suggest', {}),
  saveAll: (budgets: BudgetEntry[]) => api.put<BudgetsResponse>('/budgets', { budgets }),
  create: (entry: BudgetEntry) => api.post('/budgets', entry),
  update: (id: string, patch: { limit_pounds?: number; paused?: boolean }) => api.patch(`/budgets/${id}`, patch),
  remove: (id: string) => api.delete(`/budgets/${id}`),
  /** A budget nudge is dismissed on the server (it fires once per cycle; #158). */
  dismissNudge: (id: string) => api.post(`/budgets/nudges/${id}/dismiss`),
  /** Completed cycles, oldest first; every count and verdict is the server's (T-09-9). */
  history: (cycles: number) => api.get<HistoryResponse>('/budgets/history', { params: { cycles } }),
}

export interface SyncStatusConnection {
  connection_id: string
  provider: string
  last_synced_at: string | null
  consent: string
  stale: boolean
}

export const syncStatusAPI = {
  get: () => api.get<{ connections: SyncStatusConnection[] }>('/banking/sync-status'),
}

// "Changes made by Claude" (T-08-5). Web session only on the API side.
export const auditAPI = {
  list: (cursor?: string) => api.get<AuditPage>('/audit', { params: cursor ? { cursor } : {} }),
  undo: (id: string) => api.post<AuditItem>(`/audit/${id}/undo`),
  keep: (id: string) => api.post<AuditItem>(`/audit/${id}/keep`),
}

export const bankingAPI = {
  getConnectionStatus: () => api.get('/banking/status'),
  getBankConnectionURL: () => api.get('/banking/connect'),
  getReconnectURL: (connectionId: string) =>
    api.get(`/banking/connections/${connectionId}/reconnect`),
  // Note: the OAuth code exchange happens server-side in /banking/callback,
  // which TrueLayer redirects to directly and then forwards to /dashboard.
  syncAccounts: () => api.post('/banking/sync/accounts'),
  syncTransactions: (days: number = 90) => api.post('/banking/sync/transactions', { days }),
  getAccounts: () => api.get('/banking/accounts'),
  getTransactions: (params?: TransactionQuery) =>
    api.get('/banking/transactions', { params: listParams((params ?? {}) as Record<string, unknown>) }),
  getTransactionFacets: () =>
    api.get<{ categories: string[]; merchants: string[] }>('/banking/transactions/facets'),
  updateTransaction: (transactionId: string, data: { category?: string | null; subcategory?: string | null; counts_as?: string | null }) =>
    api.patch(`/banking/transactions/${transactionId}`, data),
  disconnectAllBanks: () => api.post('/banking/disconnect'),
  disconnectBank: (connectionId: string) => api.delete(`/banking/connections/${connectionId}`),
}

// Analytics / cashflow endpoints
export interface AccountSettingUpdate {
  role?: string
  overdraft_limit?: number | null
  repayment_cadence?: string | null
  repayment_interval_months?: number | null
  repayment_day?: number | null
  repayment_anchor_date?: string | null
  repayment_strategy?: string | null
  // A decimal string from the form (never a float); numbers only from older code paths.
  repayment_fixed_amount?: number | string | null
  repayment_installments?: number | null
  pay_from_account_id?: string | null
  instalment_card?: boolean
  // Optional card APR in percent, a decimal string; null clears it (T-10-5).
  card_apr?: string | null
}

// Card statements (T-10-1..T-10-3). Money is a decimal string; dates are ISO.
export interface CardStatement {
  id: string
  account_id: string
  statement_balance: string
  statement_date: string
  due_date: string
  minimum_due: string | null
  source: 'manual' | 'provider'
}

export interface CardStatementPosition {
  statement_id: string
  source: 'manual' | 'provider'
  statement_balance: string
  statement_date: string
  due_date: string
  minimum_due: string | null
  payments_since_statement: string
  amount_still_due: string
  unbilled: string
  paid: boolean
}

export interface CardStatements {
  statements: CardStatement[]
  current: CardStatementPosition | null
  missing_statement: boolean
  conflict: boolean
  next_payment: { amount: string; date: string; from_account_name: string | null } | null
  // Card settings view (T-10-5): notes about the saved settings, and the stored APR.
  warnings?: RepaymentWarning[]
  card_apr?: string | null
}

/** Every field is sent on add and edit, so nothing is filled from another row. */
export interface CardStatementBody {
  statement_balance: string
  statement_date: string
  due_date: string
  minimum_due: string | null
}

export interface Nudge {
  id: string
  rank: number
  body: string
  detail: string
  source: string | null
  as_of: string | null
}

export const analyticsAPI = {
  getSummary: () => api.get('/analytics/summary'),
  // Honest observations (cash drag, FSCS) — facts with arithmetic, not advice.
  getNudges: () => api.get<Nudge[]>('/analytics/nudges'),
  getForecast: (horizon: string = 'payday') =>
    api.get('/analytics/forecast', { params: { horizon } }),
  getSpending: (
    period: string = 'since_payday', frm?: string, to?: string,
    opts: {
      excludeCommitments?: boolean; lens?: string; hideTransfers?: boolean; hideCardPayments?: boolean
      // Scope the category + merchant breakdown to the active drill.
      accountId?: string; kind?: string
    } = {},
  ) =>
    api.get('/analytics/spending', {
      params: {
        period, frm, to,
        exclude_commitments: opts.excludeCommitments || undefined,
        lens: opts.lens || undefined,
        hide_transfers: opts.hideTransfers || undefined,
        hide_card_payments: opts.hideCardPayments || undefined,
        account_id: opts.accountId || undefined,
        kind: opts.kind || undefined,
      },
    }),
  getSpendingTrend: (months: number = 6, excludeCommitments = false) =>
    api.get('/analytics/spending/trend', {
      params: { months, exclude_commitments: excludeCommitments || undefined },
    }),
  getCommitments: () => api.get('/analytics/commitments'),
  // Skip the next occurrence (paid early etc.) — advances it one cadence step.
  skipCommitment: (id: string) => api.post(`/analytics/commitments/${id}/skip`),
  markTransactionRecurring: (transactionId: string, cadence: string = 'monthly') =>
    api.post('/analytics/commitments/from-transaction', { transaction_id: transactionId, cadence }),
  addCommitment: (data: {
    direction: string
    label: string
    amount: number
    cadence?: string
    interval_months?: number | null
    next_date: string
    account_id?: string | null
    match_merchant?: string | null
  }) => api.post('/analytics/commitments', data),
  updateCommitment: (id: string, data: Record<string, unknown>) =>
    api.patch(`/analytics/commitments/${id}`, data),
  updateAccountSettings: (accountId: string, data: AccountSettingUpdate) =>
    api.patch(`/analytics/accounts/${accountId}/settings`, data),
  getPlannedItems: () => api.get('/analytics/planned-items'),
  addPlannedItem: (data: Record<string, unknown>) => api.post('/analytics/planned-items', data),
  deletePlannedItem: (id: string) => api.delete(`/analytics/planned-items/${id}`),
  // The user ticks or unticks "Card payment" (T-12-4a; web only, never Claude).
  setPlannedCardPayment: (id: string, isCardPayment: boolean) =>
    api.patch(`/analytics/planned-items/${id}`, { is_card_payment: isCardPayment }),
  // Scheduled credit-card repayments (the `scheduled` repayment strategy).
  getRepayments: (accountId: string) => api.get(`/analytics/accounts/${accountId}/repayments`),
  addRepayment: (accountId: string, data: { due_date: string; amount: number }) =>
    api.post(`/analytics/accounts/${accountId}/repayments`, data),
  deleteRepayment: (accountId: string, itemId: string) =>
    api.delete(`/analytics/accounts/${accountId}/repayments/${itemId}`),
  getStatements: (accountId: string) => api.get<CardStatements>(`/analytics/accounts/${accountId}/statements`),
  addStatement: (accountId: string, body: CardStatementBody) =>
    api.post<CardStatement>(`/analytics/accounts/${accountId}/statements`, body),
  updateStatement: (accountId: string, statementId: string, body: CardStatementBody) =>
    api.patch<CardStatement>(`/analytics/accounts/${accountId}/statements/${statementId}`, body),
  deleteStatement: (accountId: string, statementId: string) =>
    api.delete(`/analytics/accounts/${accountId}/statements/${statementId}`),
  useStatement: (accountId: string, statementId: string) =>
    api.put(`/analytics/accounts/${accountId}/statements/${statementId}/in-use`),
  // Convert a purchase into a payment plan ("pay on finance").
  payOnFinance: (data: { transaction_id: string; months: number; monthly_amount: number; start_date: string }) =>
    api.post('/analytics/planned/from-transaction', data),
}

export default api
