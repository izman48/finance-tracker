import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Banknote,
  CalendarClock,
  Landmark,
  PiggyBank,
  Plug,
  RefreshCw,
  Settings2,
  ShieldAlert,
} from 'lucide-react'
import { authApi, bankingAPI, analyticsAPI, AccountSettingUpdate } from '../services/api'
import ForecastChart from '../components/ForecastChart'
import SpendingSnapshot from '../components/SpendingSnapshot'
import PlannedItems from '../components/PlannedItems'
import AnimatedNumber from '../components/ui/AnimatedNumber'
import useReveal from '../components/ui/useReveal'

interface BankConnection {
  id: string
  provider_name: string
  is_expired: boolean
  expires_at: string | null
}

interface BankStatus {
  is_connected: boolean
  connections_count: number
  last_synced_at: string | null
  connections: BankConnection[]
  message: string
}

function timeAgo(iso: string | null) {
  if (!iso) return null
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
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
  repayment_fixed_amount: number | null
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

const ROLE_META: Record<string, { label: string; chip: string }> = {
  spending: { label: 'Spending', chip: 'chip-info' },
  savings: { label: 'Savings', chip: 'chip-pos' },
  credit: { label: 'Credit card', chip: 'chip-warn' },
  excluded: { label: 'Excluded', chip: 'chip' },
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
  const [showDeleteAccount, setShowDeleteAccount] = useState(false)
  const [forecastKey, setForecastKey] = useState(0)

  const revealRef = useReveal(!!summary)

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
  const safeToSpendNegative = (summary?.safe_to_spend ?? 0) < 0

  return (
    <div ref={revealRef} className="max-w-7xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex items-baseline justify-between mb-6 sm:mb-8">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Today</h1>
        {bankStatus?.last_synced_at && (
          <span className="text-xs text-slate-500">
            Synced {timeAgo(bankStatus.last_synced_at)}
          </span>
        )}
      </div>

      {message && (
        <div className={`mb-6 ${message.toLowerCase().includes('failed') ? 'banner-err' : 'banner-ok'}`}>
          {message}
        </div>
      )}

      {/* First-run: nothing connected yet */}
      {!hasAccounts && (
        <div className="card-pad text-center py-14 sm:py-20 mb-8">
          <span className="inline-flex w-14 h-14 rounded-2xl bg-accent/15 border border-accent/25 items-center justify-center mb-5">
            <Plug className="w-7 h-7 text-accent" />
          </span>
          <h2 className="font-display font-semibold text-xl text-slate-100 mb-2">
            Connect your first bank
          </h2>
          <p className="text-sm text-slate-400 max-w-md mx-auto mb-6">
            Link your current accounts, savings and credit cards via open banking. Your history syncs
            automatically, and the dashboard fills in from there.
          </p>
          <button className="btn-primary !px-6 !py-3" onClick={handleConnectBank} disabled={loading}>
            {loading ? 'Connecting…' : 'Connect bank'}
          </button>
        </div>
      )}

      {/* Cashflow summary */}
      {summary && hasAccounts && (
        <div className="mb-6 grid lg:grid-cols-3 gap-4 sm:gap-6">
          {/* Safe to spend hero */}
          <div className="lg:col-span-2 card p-6 sm:p-8 relative overflow-hidden" data-reveal>
            <div className="orb w-72 h-72 bg-accent/15 -top-24 -right-20" />
            <div className="relative">
              <div className="text-sm text-slate-400 mb-2">Safe to spend</div>
              <div
                className={`stat-figure text-5xl sm:text-6xl ${
                  safeToSpendNegative ? 'text-neg' : 'text-slate-50'
                }`}
              >
                <AnimatedNumber value={summary.safe_to_spend} />
              </div>
              <div className="text-sm text-slate-500 mt-2">
                until {summary.next_payday ? `payday on ${formatDate(summary.next_payday)}` : 'next 30 days'}
              </div>

              <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
                {[
                  { icon: Banknote, label: 'Available cash', value: formatCurrency(summary.available_cash), tone: 'text-slate-100' },
                  { icon: CalendarClock, label: 'Committed soon', value: `−${formatCurrency(summary.committed_before_payday)}`, tone: 'text-neg' },
                  { icon: PiggyBank, label: 'Savable (30d)', value: formatCurrency(summary.savable), tone: 'text-pos' },
                  { icon: ShieldAlert, label: 'Overdraft cushion', value: formatCurrency(summary.overdraft_cushion), tone: 'text-slate-400' },
                ].map((s) => (
                  <div key={s.label}>
                    <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                      <s.icon className="w-3.5 h-3.5" />
                      {s.label}
                    </div>
                    <div className={`font-semibold tnum ${s.tone}`}>{s.value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Owed / scheduled */}
          <div className="card-pad" data-reveal>
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-sm text-slate-400">Owed on credit</span>
              <span className="stat-figure text-2xl text-slate-50">{formatCurrency(summary.credit_owed)}</span>
            </div>
            {summary.next_repayments.length > 0 ? (
              <ul className="space-y-2.5 mt-4">
                {summary.next_repayments.map((r) => (
                  <li key={r.account_id} className="flex justify-between text-sm">
                    <span className="text-slate-300">{r.label}</span>
                    <span className="text-slate-100 tnum">
                      {formatCurrency(r.amount)}{' '}
                      <span className="text-slate-500">· {formatDate(r.due_date)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500 mt-4">
                {summary.credit_owed > 0
                  ? 'Set a repayment schedule on your credit cards to forecast their bills.'
                  : 'No credit balances.'}
              </p>
            )}
            <div className="mt-5 pt-4 border-t border-white/[0.06] text-sm flex justify-between items-center">
              <span className="text-slate-400">Net worth</span>
              <Link to="/networth" className="font-semibold text-slate-100 tnum hover:text-accent transition-colors">
                {formatCurrency(summary.net_worth)} →
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* Balance forecast graph + spending snapshot */}
      {summary && hasAccounts && (
        <div className="mb-6 grid lg:grid-cols-3 gap-4 sm:gap-6">
          <div className="lg:col-span-2" data-reveal>
            <ForecastChart refreshKey={forecastKey} />
          </div>
          <div data-reveal>
            <SpendingSnapshot refreshKey={forecastKey} />
          </div>
        </div>
      )}

      {/* Planned expenses / payment plans */}
      {summary && hasAccounts && (
        <div className="mb-6" data-reveal>
          <PlannedItems onChanged={loadSummary} />
        </div>
      )}

      {/* Accounts with role + config */}
      {summary && hasAccounts && (
        <div className="mb-10" data-reveal>
          <h2 className="font-display font-semibold text-lg text-slate-100 mb-3">Accounts</h2>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {summary.accounts.map((account) => {
              const role = ROLE_META[account.role] ?? { label: account.role, chip: 'chip' }
              return (
                <div key={account.id} className="card p-5 group">
                  <div className="flex items-start justify-between mb-3">
                    <div className="min-w-0">
                      <h3 className="font-semibold text-slate-100 truncate">{account.display_name}</h3>
                      <p className="text-xs text-slate-500">{account.provider_name}</p>
                    </div>
                    <span className={role.chip}>{role.label}</span>
                  </div>
                  <p className="stat-figure text-2xl text-slate-50">
                    {formatCurrency(account.current_balance)}
                  </p>
                  {account.overdraft_limit ? (
                    <p className="text-xs text-slate-500 mt-1">
                      Overdraft: {formatCurrency(account.overdraft_limit)}
                    </p>
                  ) : null}
                  <button
                    onClick={() => setSettingsAccount(account)}
                    className="mt-3 inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-accent transition-colors"
                  >
                    <Settings2 className="w-4 h-4" /> Configure
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Bank connections management */}
      <div className="mb-8" data-reveal>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <div>
            <h2 className="font-display font-semibold text-lg text-slate-100">Connected banks</h2>
            {bankStatus?.last_synced_at && (
              <p className="text-sm text-slate-500">
                Synced {timeAgo(bankStatus.last_synced_at)} · auto-syncs every few hours
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" onClick={handleConnectBank} disabled={loading}>
              <Plug className="w-4 h-4" />
              {loading ? 'Connecting…' : 'Connect bank'}
            </button>
            {isConnected && (
              <>
                <button className="btn-ghost" onClick={handleSync} disabled={syncing}>
                  <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
                  {syncing ? 'Syncing…' : 'Sync all'}
                </button>
                <button className="btn-danger" onClick={handleDisconnectAll} disabled={loading || syncing}>
                  Disconnect all
                </button>
              </>
            )}
          </div>
        </div>

        {bankStatus?.connections && bankStatus.connections.length > 0 ? (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {bankStatus.connections.map((conn) => (
              <div key={conn.id} className="card p-5 flex items-center gap-3">
                <span className="w-10 h-10 rounded-xl bg-white/[0.06] flex items-center justify-center">
                  <Landmark className="w-5 h-5 text-slate-400" />
                </span>
                <div>
                  <h3 className="font-semibold text-slate-100">{conn.provider_name}</h3>
                  <p className={`text-sm ${conn.is_expired ? 'text-neg' : 'text-pos'}`}>
                    {conn.is_expired ? 'Needs reconnection — use Connect bank' : 'Active'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        ) : (
          hasAccounts && (
            <div className="card p-8 text-center text-slate-500 text-sm">
              No banks connected. Click "Connect bank" to get started.
            </div>
          )
        )}
      </div>

      {/* Danger zone */}
      <div className="mt-16 pt-6 border-t border-white/[0.06]">
        <button
          onClick={() => setShowDeleteAccount(true)}
          className="text-sm text-slate-600 hover:text-neg transition-colors"
        >
          Delete my account and all data
        </button>
      </div>

      {showDeleteAccount && <DeleteAccountModal onClose={() => setShowDeleteAccount(false)} />}

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

function DeleteAccountModal({ onClose }: { onClose: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async () => {
    setError('')
    setDeleting(true)
    try {
      await authApi.deleteAccount(password)
      localStorage.removeItem('token')
      window.location.href = '/'
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete account')
      setDeleting(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-neg mb-2">Delete account</h3>
        <p className="text-sm text-slate-400 mb-4">
          This permanently deletes your account, bank connections, accounts, and every
          transaction. There is no undo. Enter your password to confirm.
        </p>

        {error && <div className="banner-err mb-3">{error}</div>}

        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Current password"
          className="input mb-4"
          autoFocus
        />

        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button onClick={handleDelete} disabled={deleting || !password} className="btn-danger">
            {deleting ? 'Deleting…' : 'Delete everything'}
          </button>
        </div>
      </div>
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
    repayment_fixed_amount: account.repayment_fixed_amount ?? undefined,
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
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">{account.display_name}</h3>
        <p className="text-sm text-slate-400 mb-4">Configure how this account is treated.</p>

        <label className="label">Role</label>
        <select
          value={form.role}
          onChange={(e) => set({ role: e.target.value })}
          className="input mb-4"
        >
          <option value="spending">Spending (counts in safe-to-spend)</option>
          <option value="savings">Savings (earmarked)</option>
          <option value="credit">Credit card (owed, repaid on schedule)</option>
          <option value="excluded">Excluded</option>
        </select>

        {form.role === 'spending' && (
          <div className="mb-4">
            <label className="label">Overdraft limit (£)</label>
            <input
              type="number"
              value={form.overdraft_limit ?? ''}
              onChange={(e) => set({ overdraft_limit: e.target.value === '' ? null : Number(e.target.value) })}
              className="input"
              placeholder="0"
            />
          </div>
        )}

        {form.role === 'credit' && (
          <div className="space-y-3 mb-4">
            <div>
              <label className="label">How is it repaid?</label>
              <select
                value={form.repayment_strategy ?? 'full_balance'}
                onChange={(e) => set({ repayment_strategy: e.target.value })}
                className="input"
              >
                <option value="full_balance">Pay the full balance each cycle (e.g. Amex)</option>
                <option value="fixed">Pay a fixed amount each month</option>
                <option value="installments">Pay the balance off in installments (e.g. Monzo Flex)</option>
                <option value="scheduled">Scheduled payments (set each amount &amp; date)</option>
              </select>
            </div>

            {form.repayment_strategy === 'fixed' && (
              <div>
                <label className="label">Amount paid each cycle (£)</label>
                <input
                  type="number" min={0} step="0.01"
                  value={form.repayment_fixed_amount ?? ''}
                  onChange={(e) => set({ repayment_fixed_amount: e.target.value === '' ? null : Number(e.target.value) })}
                  className="input"
                  placeholder="e.g. 200"
                />
                {account.current_balance && form.repayment_fixed_amount ? (
                  <p className="text-xs text-slate-500 mt-1">
                    {(() => {
                      const owed = Math.abs(account.current_balance)
                      const months = Math.ceil(owed / Math.max(form.repayment_fixed_amount, 1))
                      const gbp = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(owed)
                      return `≈ ${months} month${months !== 1 ? 's' : ''} to clear the current ${gbp} balance`
                    })()}
                  </p>
                ) : null}
              </div>
            )}

            {(form.repayment_strategy === 'full_balance' || form.repayment_strategy === 'fixed') && (
              <>
                <div>
                  <label className="label">Repayment cycle</label>
                  <select
                    value={form.repayment_cadence ?? 'end_of_month'}
                    onChange={(e) => set({ repayment_cadence: e.target.value })}
                    className="input"
                  >
                    <option value="end_of_month">End of month</option>
                    <option value="monthly">Monthly on a day</option>
                    <option value="weekly">Weekly</option>
                  </select>
                </div>
                {form.repayment_cadence === 'monthly' && (
                  <div>
                    <label className="label">Payment day of month</label>
                    <input
                      type="number" min={1} max={31}
                      value={form.repayment_day ?? ''}
                      onChange={(e) => set({ repayment_day: e.target.value === '' ? null : Number(e.target.value) })}
                      className="input"
                    />
                  </div>
                )}
              </>
            )}

            {form.repayment_strategy === 'installments' && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Number of payments</label>
                  <input
                    type="number" min={1}
                    value={form.repayment_installments ?? 3}
                    onChange={(e) => set({ repayment_installments: Number(e.target.value) })}
                    className="input"
                  />
                </div>
                <div>
                  <label className="label">First payment</label>
                  <input
                    type="date"
                    value={form.repayment_anchor_date ?? ''}
                    onChange={(e) => set({ repayment_anchor_date: e.target.value || null })}
                    className="input"
                  />
                </div>
                {account.current_balance ? (
                  <p className="col-span-2 text-xs text-slate-500">
                    {new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(
                      Math.abs(account.current_balance) / (form.repayment_installments || 1)
                    )}{' '}
                    per month × {form.repayment_installments || 1}
                  </p>
                ) : null}
              </div>
            )}

            {form.repayment_strategy === 'scheduled' && (
              <ScheduledRepaymentsEditor accountId={account.id} />
            )}

            <div>
              <label className="label">Paid from</label>
              <select
                value={form.pay_from_account_id ?? ''}
                onChange={(e) => set({ pay_from_account_id: e.target.value || null })}
                className="input"
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
          <button onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

interface RepaymentItem {
  id: string
  due_date: string
  amount: number
}

// Editor for the `scheduled` repayment strategy: a list of explicit
// date+amount payments the user intends to make. Each add/remove hits the API
// immediately (they belong to the account, not the settings form being saved).
function ScheduledRepaymentsEditor({ accountId }: { accountId: string }) {
  const [items, setItems] = useState<RepaymentItem[]>([])
  const [date, setDate] = useState('')
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)

  const gbp = (n: number) =>
    new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n)

  const load = async () => {
    try {
      const res = await analyticsAPI.getRepayments(accountId)
      setItems(res.data.map((r: RepaymentItem) => ({ ...r, amount: Number(r.amount) })))
    } catch (e) {
      console.error('Failed to load scheduled repayments', e)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId])

  const add = async () => {
    if (!date || !amount || Number(amount) <= 0) return
    setBusy(true)
    try {
      await analyticsAPI.addRepayment(accountId, { due_date: date, amount: Number(amount) })
      setDate('')
      setAmount('')
      await load()
    } catch (e) {
      console.error('Failed to add repayment', e)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: string) => {
    setBusy(true)
    try {
      await analyticsAPI.deleteRepayment(accountId, id)
      setItems((xs) => xs.filter((x) => x.id !== id))
    } catch (e) {
      console.error('Failed to remove repayment', e)
    } finally {
      setBusy(false)
    }
  }

  const total = items.reduce((s, x) => s + x.amount, 0)

  return (
    <div>
      <label className="label">Scheduled payments</label>
      {items.length > 0 ? (
        <ul className="space-y-1.5 mb-2">
          {items.map((it) => (
            <li key={it.id} className="flex items-center gap-2 text-sm">
              <span className="text-slate-300 tnum">
                {new Date(it.due_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
              </span>
              <span className="ml-auto text-slate-100 tnum">{gbp(it.amount)}</span>
              <button
                onClick={() => remove(it.id)}
                disabled={busy}
                className="text-slate-500 hover:text-neg transition-colors"
                aria-label="Remove payment"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-slate-500 mb-2">No payments scheduled yet.</p>
      )}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="input" />
        </div>
        <div className="flex-1">
          <input
            type="number" min={0} step="0.01" placeholder="£ amount"
            value={amount} onChange={(e) => setAmount(e.target.value)} className="input"
          />
        </div>
        <button onClick={add} disabled={busy || !date || !amount} className="btn-ghost shrink-0">
          Add
        </button>
      </div>
      {items.length > 0 && (
        <p className="text-xs text-slate-500 mt-1">
          {items.length} payment{items.length !== 1 ? 's' : ''} · {gbp(total)} total scheduled
        </p>
      )}
    </div>
  )
}
