import axios from 'axios'

// Unset -> local dev default; empty string -> same-origin (production behind Caddy)
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add auth token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Handle auth errors
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
  register: (email: string, password: string) =>
    api.post('/auth/register', { email, password }),

  login: (email: string, password: string) =>
    api.post('/auth/login', new URLSearchParams({ username: email, password }), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),

  me: () => api.get('/auth/me'),

  forgotPassword: (email: string) =>
    api.post('/auth/forgot-password', { email }),

  resetPassword: (token: string, newPassword: string) =>
    api.post('/auth/reset-password', { token, new_password: newPassword }),

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
  create: (data: { pattern: string; match_type: string; match_field: string; category: string; pack_id?: string | null }) =>
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
  valuations: AssetValuation[]
}

export interface NetWorthPoint {
  date: string
  bank: string
  assets: string
  net_worth: string
}

export const assetsAPI = {
  list: () => api.get<Asset[]>('/assets'),
  create: (data: { name: string; asset_type: string; value: number; valued_at?: string }) =>
    api.post('/assets', data),
  update: (id: string, data: { name?: string; asset_type?: string }) =>
    api.patch(`/assets/${id}`, data),
  remove: (id: string) => api.delete(`/assets/${id}`),
  addValuation: (id: string, data: { value: number; valued_at?: string }) =>
    api.post(`/assets/${id}/valuations`, data),
  removeValuation: (assetId: string, valuationId: string) =>
    api.delete(`/assets/${assetId}/valuations/${valuationId}`),
  netWorthHistory: (months = 12) =>
    api.get<NetWorthPoint[]>(`/analytics/net-worth-history?months=${months}`),
}

// Health check
export const healthApi = {
  check: () => api.get('/health'),
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
  getTransactions: (params?: { page?: number; page_size?: number; account_id?: string }) =>
    api.get('/banking/transactions', { params }),
  updateTransaction: (transactionId: string, data: { category?: string | null; subcategory?: string | null }) =>
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

export const analyticsAPI = {
  getSummary: () => api.get('/analytics/summary'),
  getForecast: (horizon: string = 'payday') =>
    api.get('/analytics/forecast', { params: { horizon } }),
  getSpending: (period: string = 'since_payday', frm?: string, to?: string) =>
    api.get('/analytics/spending', { params: { period, frm, to } }),
  getSpendingTrend: (months: number = 6) =>
    api.get('/analytics/spending/trend', { params: { months } }),
  getCommitments: () => api.get('/analytics/commitments'),
  markTransactionRecurring: (transactionId: string, cadence: string = 'monthly') =>
    api.post('/analytics/commitments/from-transaction', { transaction_id: transactionId, cadence }),
  addCommitment: (data: {
    direction: string
    label: string
    amount: number
    cadence?: string
    next_date: string
    account_id?: string | null
  }) => api.post('/analytics/commitments', data),
  updateCommitment: (id: string, data: Record<string, unknown>) =>
    api.patch(`/analytics/commitments/${id}`, data),
  updateAccountSettings: (accountId: string, data: AccountSettingUpdate) =>
    api.patch(`/analytics/accounts/${accountId}/settings`, data),
  getPlannedItems: () => api.get('/analytics/planned-items'),
  addPlannedItem: (data: Record<string, unknown>) => api.post('/analytics/planned-items', data),
  deletePlannedItem: (id: string) => api.delete(`/analytics/planned-items/${id}`),
}

export default api
