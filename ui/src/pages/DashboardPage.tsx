import { useEffect, useState } from 'react'
import { bankingAPI, analyticsAPI, AccountSettingUpdate } from '../services/api'
import ForecastChart from '../components/ForecastChart'
import SpendingSnapshot from '../components/SpendingSnapshot'
import PlannedItems from '../components/PlannedItems'

interface BankConnection {
  id: string
  provider_name: string
  is_expired: boolean
  expires_at: string | null
}

interface BankStatus {
  is_connected: boolean
  connections_count: number
  connections: BankConnection[]
  message: string
}

interface NextRepayment {
  account_id: string
  label: string
  amount: number
  due_date: string
}

interface SummaryAccount {
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
  repayment_installments: number | null
  pay_from_account_id: string | null
}

interface CashflowSummary {
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

const ROLE_LABELS: Record<string, string> = {
  spending: 'Spending',
  savings: 'Savings',
  credit: 'Credit card',
  excluded: 'Excluded',
}

function formatCurrency(amount: number | null, currency = 'GBP') {
  if (amount === null || amount === undefined) return 'N/A'
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency }).format(amount)
}

function formatDate(date: string | null) {
  if (!date) return '—'
  return new Date(date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

export default function DashboardPage() {
  const [bankStatus, setBankStatus] = useState<BankStatus | null>(null)
  const [summary, setSummary] = useState<CashflowSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState('')
  const [settingsAccount, setSettingsAccount] = useState<SummaryAccount | null>(null)
  const [forecastKey, setForecastKey] = useState(0)

  useEffect(() => {
    loadBankStatus()
    loadSummary()

    const params = new URLSearchParams(window.location.search)
    const bankConnected = params.get('bank_connected')
    if (bankConnected === 'true') {
      setMessage('Bank connected successfully! Historical data has been synced automatically.')
      loadSummary()
      window.history.replaceState({}, '', '/dashboard')
    } else if (bankConnected === 'false') {
      setMessage('Failed to connect bank. Please try again.')
      window.history.replaceState({}, '', '/dashboard')
    }
  }, [])

  const loadBankStatus = async () => {
    try {
      const response = await bankingAPI.getConnectionStatus()
      setBankStatus(response.data)
    } catch (error) {
      console.error('Failed to load bank status:', error)
    }
  }

  const loadSummary = async () => {
    try {
      const response = await analyticsAPI.getSummary()
      setSummary(response.data)
      setForecastKey((k) => k + 1)
    } catch (error) {
      console.error('Failed to load cashflow summary:', error)
    }
  }

  const handleConnectBank = async () => {
    setLoading(true)
    setMessage('')
    try {
      const response = await bankingAPI.getBankConnectionURL()
      window.location.href = response.data.auth_url
    } catch (error: any) {
      setMessage('Failed to get bank connection URL: ' + (error.response?.data?.detail || error.message))
      setLoading(false)
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    setMessage('')
    try {
      await bankingAPI.syncAccounts()
      await bankingAPI.syncTransactions(1825)
      await loadSummary()
      setMessage('Accounts and transactions synced.')
    } catch (error: any) {
      setMessage('Failed to sync: ' + (error.response?.data?.detail || error.message))
    } finally {
      setSyncing(false)
    }
  }

  const handleDisconnectAll = async () => {
    if (!confirm('Disconnect ALL banks? This deletes all accounts and transactions.')) return
    setLoading(true)
    try {
      const response = await bankingAPI.disconnectAllBanks()
      setMessage(response.data.message)
      setBankStatus(null)
      await loadBankStatus()
      await loadSummary()
    } catch (error: any) {
      setMessage('Failed to disconnect: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  const isConnected = bankStatus?.is_connected
  const hasAccounts = (summary?.accounts.length ?? 0) > 0

  return (
    <div className="max-w-7xl mx-auto px-4 py-8">
      <h1 className="text-2xl sm:text-3xl font-bold mb-6 sm:mb-8">Dashboard</h1>

      {message && (
        <div className={`mb-6 p-4 rounded-lg ${
          message.toLowerCase().includes('failed') ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'
        }`}>
          {message}
        </div>
      )}

      {/* Cashflow summary */}
      {summary && hasAccounts && (
        <div className="mb-8 grid lg:grid-cols-3 gap-6">
          {/* Safe to spend */}
          <div className="lg:col-span-2 p-6 bg-white rounded-xl shadow-sm border border-gray-200">
            <div className="text-sm text-gray-500 mb-1">Safe to spend</div>
            <div className="text-4xl sm:text-5xl font-bold text-gray-900">{formatCurrency(summary.safe_to_spend)}</div>
            <div className="text-sm text-gray-500 mt-1">
              until {summary.next_payday ? formatDate(summary.next_payday) : 'next 30 days'}
            </div>
            <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <div className="flex justify-between border-t pt-2">
                <span className="text-gray-600">Available cash</span>
                <span className="font-semibold">{formatCurrency(summary.available_cash)}</span>
              </div>
              <div className="flex justify-between border-t pt-2">
                <span className="text-gray-600">Committed soon</span>
                <span className="font-semibold text-red-600">−{formatCurrency(summary.committed_before_payday)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Overdraft cushion</span>
                <span className="font-semibold text-gray-500">{formatCurrency(summary.overdraft_cushion)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Savable (30d)</span>
                <span className="font-semibold text-green-600">{formatCurrency(summary.savable)}</span>
              </div>
            </div>
          </div>

          {/* Owed / scheduled */}
          <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-sm text-gray-500">Owed (scheduled)</span>
              <span className="text-xl font-bold text-gray-900">{formatCurrency(summary.credit_owed)}</span>
            </div>
            {summary.next_repayments.length > 0 ? (
              <ul className="space-y-2 mt-3">
                {summary.next_repayments.map((r) => (
                  <li key={r.account_id} className="flex justify-between text-sm">
                    <span className="text-gray-700">{r.label}</span>
                    <span className="text-gray-900">
                      {formatCurrency(r.amount)} <span className="text-gray-400">· {formatDate(r.due_date)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-400 mt-3">
                {summary.credit_owed > 0
                  ? 'Set a repayment schedule on your credit cards to forecast their bills.'
                  : 'No credit balances.'}
              </p>
            )}
            <div className="mt-4 pt-3 border-t text-sm flex justify-between">
              <span className="text-gray-600">Net worth</span>
              <span className="font-semibold">{formatCurrency(summary.net_worth)}</span>
            </div>
          </div>
        </div>
      )}

      {/* Balance forecast graph + spending snapshot */}
      {summary && hasAccounts && (
        <div className="mb-8 grid lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <ForecastChart refreshKey={forecastKey} />
          </div>
          <SpendingSnapshot refreshKey={forecastKey} />
        </div>
      )}

      {/* Planned expenses / payment plans */}
      {summary && hasAccounts && (
        <div className="mb-8">
          <PlannedItems onChanged={loadSummary} />
        </div>
      )}

      {/* Accounts with role + config */}
      {summary && hasAccounts && (
        <div className="mb-8">
          <h2 className="text-2xl font-semibold mb-4">Your Accounts</h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {summary.accounts.map((account) => (
              <div key={account.id} className="p-5 bg-white rounded-xl shadow-sm border border-gray-200">
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h3 className="font-semibold">{account.display_name}</h3>
                    <p className="text-xs text-gray-500">{account.provider_name}</p>
                  </div>
                  <span className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded">
                    {ROLE_LABELS[account.role] ?? account.role}
                  </span>
                </div>
                <p className="text-2xl font-bold">{formatCurrency(account.current_balance)}</p>
                {account.overdraft_limit ? (
                  <p className="text-xs text-gray-500 mt-1">
                    Overdraft: {formatCurrency(account.overdraft_limit)}
                  </p>
                ) : null}
                <button
                  onClick={() => setSettingsAccount(account)}
                  className="mt-3 text-sm text-blue-600 hover:text-blue-800"
                >
                  Configure
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Bank connections management */}
      <div className="mb-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <h2 className="text-2xl font-semibold">Connected Banks</h2>
          <div className="flex flex-wrap gap-2">
            <button
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              onClick={handleConnectBank}
              disabled={loading}
            >
              {loading ? 'Connecting...' : 'Connect Bank'}
            </button>
            {isConnected && (
              <>
                <button
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                  onClick={handleSync}
                  disabled={syncing}
                >
                  {syncing ? 'Syncing...' : 'Sync All'}
                </button>
                <button
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                  onClick={handleDisconnectAll}
                  disabled={loading || syncing}
                >
                  Disconnect All
                </button>
              </>
            )}
          </div>
        </div>

        {bankStatus?.connections && bankStatus.connections.length > 0 ? (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {bankStatus.connections.map((conn) => (
              <div key={conn.id} className="p-5 bg-white rounded-xl shadow-sm border border-gray-200">
                <h3 className="font-semibold">{conn.provider_name}</h3>
                <p className={`text-sm mt-1 ${conn.is_expired ? 'text-red-600' : 'text-green-600'}`}>
                  {conn.is_expired ? 'Token expired' : 'Active'}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 bg-white rounded-xl shadow-sm text-center text-gray-500">
            No banks connected. Click "Connect Bank" to get started.
          </div>
        )}
      </div>

      {settingsAccount && (
        <AccountSettingsModal
          account={settingsAccount}
          spendingAccounts={summary?.accounts.filter((a) => a.role === 'spending') ?? []}
          onClose={() => setSettingsAccount(null)}
          onSaved={async () => {
            setSettingsAccount(null)
            await loadSummary()
          }}
        />
      )}
    </div>
  )
}

function AccountSettingsModal({
  account,
  spendingAccounts,
  onClose,
  onSaved,
}: {
  account: SummaryAccount
  spendingAccounts: SummaryAccount[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState<AccountSettingUpdate>({
    role: account.role,
    overdraft_limit: account.overdraft_limit ?? undefined,
    repayment_cadence: account.repayment_cadence ?? 'end_of_month',
    repayment_day: account.repayment_day ?? undefined,
    repayment_interval_months: account.repayment_interval_months ?? undefined,
    repayment_anchor_date: account.repayment_anchor_date ?? undefined,
    repayment_strategy: account.repayment_strategy ?? 'full_balance',
    repayment_installments: account.repayment_installments ?? 3,
    pay_from_account_id: account.pay_from_account_id ?? undefined,
  })
  const [saving, setSaving] = useState(false)

  const set = (patch: Partial<AccountSettingUpdate>) => setForm((f) => ({ ...f, ...patch }))

  const save = async () => {
    setSaving(true)
    const payload: AccountSettingUpdate = { ...form }
    if (form.role === 'credit' && form.repayment_strategy === 'installments') {
      // Installments step monthly from the first-payment date.
      payload.repayment_cadence = 'every_n_months'
      payload.repayment_interval_months = 1
    }
    try {
      await analyticsAPI.updateAccountSettings(account.id, payload)
      onSaved()
    } catch (e) {
      console.error('Failed to save settings', e)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">{account.display_name}</h3>
        <p className="text-sm text-gray-500 mb-4">Configure how this account is treated.</p>

        <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
        <select
          value={form.role}
          onChange={(e) => set({ role: e.target.value })}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg mb-4"
        >
          <option value="spending">Spending (counts in safe-to-spend)</option>
          <option value="savings">Savings (earmarked)</option>
          <option value="credit">Credit card (owed, repaid on schedule)</option>
          <option value="excluded">Excluded</option>
        </select>

        {form.role === 'spending' && (
          <div className="mb-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">Overdraft limit (£)</label>
            <input
              type="number"
              value={form.overdraft_limit ?? ''}
              onChange={(e) => set({ overdraft_limit: e.target.value === '' ? null : Number(e.target.value) })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
              placeholder="0"
            />
          </div>
        )}

        {form.role === 'credit' && (
          <div className="space-y-3 mb-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">How is it repaid?</label>
              <select
                value={form.repayment_strategy ?? 'full_balance'}
                onChange={(e) => set({ repayment_strategy: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
              >
                <option value="full_balance">Pay the full balance each cycle (e.g. Amex)</option>
                <option value="installments">Pay the balance off in installments (e.g. Monzo Flex)</option>
              </select>
            </div>

            {form.repayment_strategy === 'full_balance' && (
              <>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Repayment cycle</label>
                  <select
                    value={form.repayment_cadence ?? 'end_of_month'}
                    onChange={(e) => set({ repayment_cadence: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                  >
                    <option value="end_of_month">End of month</option>
                    <option value="monthly">Monthly on a day</option>
                    <option value="weekly">Weekly</option>
                  </select>
                </div>
                {form.repayment_cadence === 'monthly' && (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Payment day of month</label>
                    <input
                      type="number" min={1} max={31}
                      value={form.repayment_day ?? ''}
                      onChange={(e) => set({ repayment_day: e.target.value === '' ? null : Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                )}
              </>
            )}

            {form.repayment_strategy === 'installments' && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Number of payments</label>
                  <input
                    type="number" min={1}
                    value={form.repayment_installments ?? 3}
                    onChange={(e) => set({ repayment_installments: Number(e.target.value) })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">First payment</label>
                  <input
                    type="date"
                    value={form.repayment_anchor_date ?? ''}
                    onChange={(e) => set({ repayment_anchor_date: e.target.value || null })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                  />
                </div>
                {account.current_balance ? (
                  <p className="col-span-2 text-xs text-gray-500">
                    {new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(
                      Math.abs(account.current_balance) / (form.repayment_installments || 1)
                    )}{' '}
                    per month × {form.repayment_installments || 1}
                  </p>
                ) : null}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Paid from</label>
              <select
                value={form.pay_from_account_id ?? ''}
                onChange={(e) => set({ pay_from_account_id: e.target.value || null })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
              >
                <option value="">—</option>
                {spendingAccounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.display_name}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 mt-2">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
