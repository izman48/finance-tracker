import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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
  exchangeOAuthCode: (code: string) => api.post('/banking/exchange-code', null, { params: { code } }),
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

export default api
