import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Banknote,
  CalendarClock,
  PiggyBank,
  Plug,
  ShieldAlert,
} from 'lucide-react'
import { bankingAPI, analyticsAPI } from '../services/api'
import { BankStatus, CashflowSummary } from '../types'
import { money as formatCurrency, dateDayMonth as formatDate, timeAgo } from '../lib/format'
import ForecastChart from '../components/ForecastChart'
import SpendingSnapshot from '../components/SpendingSnapshot'
import PlannedItems from '../components/PlannedItems'
import AnimatedNumber from '../components/ui/AnimatedNumber'
import InfoTip from '../components/ui/InfoTip'
import { EXPLAIN } from '../copy/statExplainers'
import useReveal from '../components/ui/useReveal'

export default function DashboardPage() {
  const [bankStatus, setBankStatus] = useState<BankStatus | null>(null)
  const [summary, setSummary] = useState<CashflowSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [justConnected, setJustConnected] = useState(false)
  const [forecastKey, setForecastKey] = useState(0)

  const revealRef = useReveal(!!summary)

  useEffect(() => {
    loadBankStatus()
    loadSummary()

    const params = new URLSearchParams(window.location.search)
    const bankConnected = params.get('bank_connected')
    if (bankConnected === 'true') {
      setMessage('Bank connected — historical data synced automatically.')
      setJustConnected(true)
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
        <div
          className={`mb-6 flex flex-wrap items-center justify-between gap-3 ${
            message.toLowerCase().includes('failed') ? 'banner-err' : 'banner-ok'
          }`}
        >
          <span>{message}</span>
          {/* The moment right after one bank connects is the highest-intent
              moment to connect the next one. */}
          {justConnected && (
            <button onClick={handleConnectBank} disabled={loading} className="btn-ghost !py-1.5">
              {loading ? 'Connecting…' : 'Connect another bank'}
            </button>
          )}
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
              <div className="text-sm text-slate-400 mb-2 flex items-center gap-1.5">
                Safe to spend
                <InfoTip text={EXPLAIN.safeToSpend} side="bottom" align="left" />
              </div>
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
                  { icon: Banknote, label: 'Available cash', value: formatCurrency(summary.available_cash), tone: 'text-slate-100', explain: EXPLAIN.availableCash },
                  { icon: CalendarClock, label: 'Committed soon', value: `−${formatCurrency(summary.committed_before_payday)}`, tone: 'text-neg', explain: EXPLAIN.committedSoon },
                  { icon: PiggyBank, label: 'Savable (30d)', value: formatCurrency(summary.savable), tone: 'text-pos', explain: EXPLAIN.savable },
                  { icon: ShieldAlert, label: 'Overdraft cushion', value: formatCurrency(summary.overdraft_cushion), tone: 'text-slate-400', explain: EXPLAIN.overdraftCushion },
                ].map((s) => (
                  <div key={s.label}>
                    <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
                      <s.icon className="w-3.5 h-3.5" />
                      {s.label}
                      <InfoTip text={s.explain} align="left" />
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
              <span className="text-sm text-slate-400 flex items-center gap-1.5">
                Owed on credit
                <InfoTip text={EXPLAIN.creditOwed} side="bottom" align="left" />
              </span>
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
              <span className="text-slate-400 flex items-center gap-1.5">
                Net worth
                <InfoTip text={EXPLAIN.netWorth} align="left" />
              </span>
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

      {/* Accounts, connections, and account management now live on Wealth
          (the balance sheet) and in the user menu. */}
      {summary && hasAccounts && (
        <p className="text-sm text-slate-500 mb-10" data-reveal>
          Looking for your accounts and bank connections? They live on{' '}
          <Link to="/networth" className="text-accent hover:underline">
            Wealth
          </Link>{' '}
          now, as your balance sheet.
        </p>
      )}
    </div>
  )
}
