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
