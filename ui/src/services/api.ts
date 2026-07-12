import axios from 'axios'
import { isAnonymized } from '../lib/anonymize'
import { sampleResponse } from '../lib/sampleAccount'

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
    api.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),

  forgotPassword: (email: string) =>
    api.post('/auth/forgot-password', { email }),

  // Without the recovery code, resetting issues a new encryption key: bank
  // data is purged (rebuilt by re-syncing) and a fresh code comes back.
  resetPassword: (token: string, newPassword: string, recoveryCode?: string) =>
    api.post<{ message: string; recovery_code?: string }>('/auth/reset-password', {
      token,
      new_password: newPassword,
      recovery_code: recoveryCode || undefined,
    }),

  deleteAccount: (password: string) =>
    api.post('/auth/delete-account', { password }),
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

export interface Instrument {
  id: string
  symbol: string
  name: string
  kind: string      // crypto | equity | etf
  currency: string
}

export interface InstrumentSearchResult extends Instrument {
  provider: string
}

export interface Asset {
  id: string
  name: string
  asset_type: string
  // Projection assumption (%/yr, may be negative); null → projection default.
  assumed_growth_pct: string | null
  // Planned monthly saving into this asset (paydown on a liability).
  monthly_contribution: string | null
  // Live pricing (present when linked to an instrument).
  instrument: Instrument | null
  units: string | null
  unit_price_gbp: string | null
  priced_at: string | null
  valuations: AssetValuation[]
}

export interface NetWorthPoint {
  date: string
  bank: string
  assets: string
  net_worth: string
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

export const assetsAPI = {
  list: () => api.get<Asset[]>('/assets'),
  create: (data: { name: string; asset_type: string; value: number; valued_at?: string }) =>
    api.post('/assets', data),
  update: (id: string, data: { name?: string; asset_type?: string; assumed_growth_pct?: number | null; monthly_contribution?: number | null }) =>
    api.patch(`/assets/${id}`, data),
  remove: (id: string) => api.delete(`/assets/${id}`),
  addValuation: (id: string, data: { value: number; valued_at?: string }) =>
    api.post(`/assets/${id}/valuations`, data),
  removeValuation: (assetId: string, valuationId: string) =>
    api.delete(`/assets/${assetId}/valuations/${valuationId}`),
  // Record money added (+) / withdrawn (−) so growth can be told from saving.
  addFlow: (id: string, data: { amount: number; flow_date?: string }) =>
    api.post(`/assets/${id}/flows`, data),
  // Live pricing: search public instruments, link/unlink one to an asset, and
  // reprice all linked assets (snapshots today's value into a valuation).
  searchInstruments: (q: string) =>
    api.get<InstrumentSearchResult[]>('/instruments/search', { params: { q } }),
  linkInstrument: (id: string, data: { instrument_id: string; units: number }) =>
    api.post<Asset>(`/assets/${id}/link`, data),
  unlinkInstrument: (id: string) => api.post<Asset>(`/assets/${id}/unlink`),
  refreshPrices: () => api.post<Asset[]>('/assets/refresh-prices'),
  decomposition: (months = 12) =>
    api.get<AssetDecomposition>('/analytics/net-worth-decomposition', { params: { months } }),
  netWorthHistory: (months = 12) =>
    api.get<NetWorthPoint[]>(`/analytics/net-worth-history?months=${months}`),
  // A projection from stated assumptions — an estimate, not advice.
  netWorthProjection: (params: {
    target_amount?: number
    monthly_contribution?: number
    annual_growth_pct?: number
    subtract_spending?: boolean
    monthly_spending?: number
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
export const bankingAPI = {
  getConnectionStatus: () => api.get('/banking/status'),
  getBankConnectionURL: () => api.get('/banking/connect'),
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
  repayment_fixed_amount?: number | null
  repayment_installments?: number | null
  pay_from_account_id?: string | null
}

export interface Nudge {
  id: string
  rank: number
  body: string
  detail: string
  source: string
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
  // Scheduled credit-card repayments (the `scheduled` repayment strategy).
  getRepayments: (accountId: string) => api.get(`/analytics/accounts/${accountId}/repayments`),
  addRepayment: (accountId: string, data: { due_date: string; amount: number }) =>
    api.post(`/analytics/accounts/${accountId}/repayments`, data),
  deleteRepayment: (accountId: string, itemId: string) =>
    api.delete(`/analytics/accounts/${accountId}/repayments/${itemId}`),
  // Convert a purchase into a payment plan ("pay on finance").
  payOnFinance: (data: { transaction_id: string; months: number; monthly_amount: number; start_date: string }) =>
    api.post('/analytics/planned/from-transaction', data),
}

export default api
