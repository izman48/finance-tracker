import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, PieChart, Plug, RefreshCw, Sparkles, TrendingUp, Wallet } from 'lucide-react'
import { analyticsAPI, bankingAPI, assetsAPI, NetWorthPosition } from '../services/api'
import { BankStatus, CashflowSummary, Commitment, PlannedItem } from '../types'
import { gbp0 as gbp, dateDayMonth, timeAgo, changeTone, signedGbp, signedPct } from '../lib/format'
import { buildUpcoming } from '../lib/upcoming'
import AnimatedNumber from '../components/ui/AnimatedNumber'
import InfoTip from '../components/ui/InfoTip'
import { EXPLAIN } from '../copy/statExplainers'
import useReveal from '../components/ui/useReveal'

interface SpendingSnapshot {
  total: number
  // Same days of last month, for a like-for-like pace comparison.
  prevTotal: number | null
  topCategories: { category: string; total: number }[]
}

function localIso(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** One tab, summarised: a big figure, one line of context, and a few rows.
 *  The whole card is the link — tapping anywhere goes to that tab. */
function SummaryCard({
  to, icon: Icon, title, label, explain, figure, context, children,
}: {
  to: string
  icon: typeof Wallet
  title: string
  label: string
  explain: string
  figure: number
  context: ReactNode
  children?: ReactNode
}) {
  return (
    <Link
      to={to}
      data-reveal
      className="card p-5 sm:p-6 flex flex-col group hover:border-accent/30 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
    >
      <div className="flex items-center justify-between mb-4">
        <span className="flex items-center gap-2 font-display font-semibold text-slate-100">
          <span className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/20 flex items-center justify-center">
            <Icon className="w-4 h-4 text-accent" />
          </span>
          {title}
        </span>
        <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-accent transition-colors" />
      </div>
      <div className="text-xs text-slate-500 mb-1 flex items-center gap-1.5">
        {label}
        <InfoTip text={explain} side="bottom" align="left" />
      </div>
      <div className="stat-figure text-3xl sm:text-4xl text-slate-50">
        <AnimatedNumber value={figure} format={gbp} />
      </div>
      <div className="text-sm mt-1.5">{context}</div>
      {children && <div className="mt-4 pt-4 border-t border-white/[0.06] text-sm space-y-2">{children}</div>}
    </Link>
  )
}

export default function OverviewPage() {
  const [bankStatus, setBankStatus] = useState<BankStatus | null>(null)
  const [summary, setSummary] = useState<CashflowSummary | null>(null)
  const [commitments, setCommitments] = useState<Commitment[]>([])
  const [planned, setPlanned] = useState<PlannedItem[]>([])
  const [spending, setSpending] = useState<SpendingSnapshot | null>(null)
  const [position, setPosition] = useState<NetWorthPosition | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [message, setMessage] = useState('')

  const revealRef = useReveal(loaded)

  useEffect(() => {
    const now = new Date()
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1)
    const prevStart = new Date(now.getFullYear(), now.getMonth() - 1, 1)
    const prevMonthDays = new Date(now.getFullYear(), now.getMonth(), 0).getDate()
    const prevEnd = new Date(now.getFullYear(), now.getMonth() - 1, Math.min(now.getDate(), prevMonthDays))

    const load = async () => {
      // Each source fails independently: a broken spending call shouldn't blank
      // the cash and wealth cards.
      const [b, s, c, p, sp, prev, pos] = await Promise.allSettled([
        bankingAPI.getConnectionStatus(),
        analyticsAPI.getSummary(),
        analyticsAPI.getCommitments(),
        analyticsAPI.getPlannedItems(),
        analyticsAPI.getSpending('custom', localIso(monthStart), localIso(now)),
        analyticsAPI.getSpending('custom', localIso(prevStart), localIso(prevEnd)),
        assetsAPI.netWorthPosition(),
      ])
      if (b.status === 'fulfilled') setBankStatus(b.value.data)
      if (s.status === 'fulfilled') setSummary(s.value.data)
      if (c.status === 'fulfilled') setCommitments(c.value.data)
      if (p.status === 'fulfilled') setPlanned(p.value.data)
      if (sp.status === 'fulfilled') {
        const d = sp.value.data
        setSpending({
          total: Number(d.total_spent),
          prevTotal: prev.status === 'fulfilled' ? Number(prev.value.data.total_spent) : null,
          topCategories: (d.by_category as { category: string; total: string }[])
            .map((x) => ({ category: x.category, total: Number(x.total) }))
            .sort((a, b) => b.total - a.total)
            .slice(0, 3),
        })
      }
      if (pos.status === 'fulfilled') setPosition(pos.value.data)
      setLoaded(true)
    }
    load()
  }, [])

  const handleConnectBank = async () => {
    setConnecting(true)
    setMessage('')
    try {
      const response = await bankingAPI.getBankConnectionURL()
      window.location.href = response.data.auth_url
    } catch (error: any) {
      setMessage('Failed to get bank connection URL: ' + (error.response?.data?.detail || error.message))
      setConnecting(false)
    }
  }

  const hasAccounts = (summary?.accounts.length ?? 0) > 0
  const listedAccounts = (summary?.accounts ?? []).filter((a) => a.role !== 'excluded')
  const cashAccounts = listedAccounts.filter((a) => a.role === 'spending' || a.role === 'savings')
  const totalCash = cashAccounts.reduce((sum, a) => sum + Number(a.current_balance ?? 0), 0)
  const safeToSpend = Number(summary?.safe_to_spend ?? 0)
  const suggestedCount = commitments.filter((c) => c.status === 'suggested').length
  const today = localIso(new Date())
  const upcoming = buildUpcoming(commitments, summary?.next_repayments ?? [], planned, today, 3)

  const spendDelta = spending && spending.prevTotal !== null ? spending.total - spending.prevTotal : null
  const monthName = new Date().toLocaleDateString('en-GB', { month: 'long' })

  const byKey = Object.fromEntries((position?.changes ?? []).map((c) => [c.key, c]))
  const oneMonth = byKey['1m']
  const oneYear = byKey['1y']
  const netWorth = position ? Number(position.net_worth) : Number(summary?.net_worth ?? 0)

  if (!loaded) {
    return <div className="max-w-7xl mx-auto px-4 py-8 text-center text-slate-500">Loading your overview…</div>
  }

  return (
    <div ref={revealRef} className="max-w-7xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex items-baseline justify-between mb-6 sm:mb-8">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Home</h1>
        {bankStatus?.last_synced_at && (
          <span className="text-xs text-slate-500 inline-flex items-center gap-1.5">
            <RefreshCw className="w-3.5 h-3.5" />
            Synced {timeAgo(bankStatus.last_synced_at)}
          </span>
        )}
      </div>

      {message && <div className="mb-6 banner-err">{message}</div>}

      {suggestedCount > 0 && (
        <Link
          to="/commitments"
          className="mb-6 flex items-center justify-between gap-3 card px-4 py-3 hover:border-accent/25 transition-colors"
        >
          <span className="flex items-center gap-2 text-sm text-slate-200">
            <Sparkles className="w-4 h-4 text-accent" />
            {suggestedCount} recurring payment{suggestedCount !== 1 ? 's' : ''} detected — review to
            keep safe-to-spend accurate
          </span>
          <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />
        </Link>
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
            automatically, and this overview fills in from there.
          </p>
          <button className="btn-primary !px-6 !py-3" onClick={handleConnectBank} disabled={connecting}>
            {connecting ? 'Connecting…' : 'Connect bank'}
          </button>
        </div>
      )}

      {/* The three questions, one card each. Every card opens its tab. */}
      {hasAccounts && summary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-6">
          <SummaryCard
            to="/dashboard"
            icon={Wallet}
            title="Cashflow"
            label="Total cash"
            explain={EXPLAIN.totalCash}
            figure={totalCash}
            context={
              <span className={safeToSpend < 0 ? 'text-neg' : 'text-slate-400'}>
                <span className={`tnum font-semibold ${safeToSpend < 0 ? 'text-neg' : 'text-slate-100'}`}>
                  {gbp(safeToSpend)}
                </span>{' '}
                safe to spend until{' '}
                {summary.next_payday ? `payday on ${dateDayMonth(summary.next_payday)}` : 'next month'}
              </span>
            }
          >
            {upcoming.length > 0 ? (
              upcoming.map((u) => (
                <div key={u.key} className="flex items-baseline justify-between gap-3">
                  <span className="text-slate-300 min-w-0 truncate">{u.label}</span>
                  <span className={`tnum shrink-0 ${u.income ? 'text-pos' : 'text-slate-100'}`}>
                    {u.income ? '+' : ''}{gbp(u.amount)}{' '}
                    <span className="text-slate-500">· {dateDayMonth(u.date)}</span>
                  </span>
                </div>
              ))
            ) : (
              <div className="text-slate-500">Nothing scheduled yet — confirm your bills and income.</div>
            )}
          </SummaryCard>

          <SummaryCard
            to="/insights"
            icon={PieChart}
            title="Spending"
            label={`Money out in ${monthName}`}
            explain={EXPLAIN.moneyOut}
            figure={spending?.total ?? 0}
            context={
              spendDelta === null ? (
                <span className="text-slate-400">so far this month</span>
              ) : spendDelta === 0 ? (
                <span className="text-slate-400">same as this point last month</span>
              ) : (
                <span className={spendDelta < 0 ? 'text-pos' : 'text-warn'}>
                  {gbp(Math.abs(spendDelta))} {spendDelta < 0 ? 'less' : 'more'} than this point last month
                </span>
              )
            }
          >
            {spending && spending.topCategories.length > 0 ? (
              spending.topCategories.map((c) => (
                <div key={c.category} className="flex items-baseline justify-between gap-3">
                  <span className="text-slate-300 min-w-0 truncate">{c.category}</span>
                  <span className="tnum text-slate-100 shrink-0">{gbp(c.total)}</span>
                </div>
              ))
            ) : (
              <div className="text-slate-500">No spending recorded this month yet.</div>
            )}
          </SummaryCard>

          <SummaryCard
            to="/networth"
            icon={TrendingUp}
            title="Wealth"
            label="Net worth"
            explain={EXPLAIN.netWorth}
            figure={netWorth}
            context={
              oneMonth?.available ? (
                <span className={changeTone(Number(oneMonth.change))}>
                  <span className="tnum font-semibold">{signedGbp(Number(oneMonth.change))}</span>
                  {oneMonth.change_pct !== null && (
                    <span className="tnum"> ({signedPct(oneMonth.change_pct)})</span>
                  )}{' '}
                  <span className="text-slate-400">this month</span>
                </span>
              ) : (
                <span className="text-slate-400">tracking starts today — check back next month</span>
              )
            }
          >
            {[{ label: 'Past year', c: oneYear }, { label: 'All time', c: byKey['all'] }]
              .filter((x) => x.c)
              .map(({ label, c }) => (
                <div key={c.key} className="flex items-baseline justify-between gap-3">
                  <span className="text-slate-300">{label}</span>
                  {c.available ? (
                    <span className={`tnum shrink-0 ${changeTone(Number(c.change))}`}>
                      {signedGbp(Number(c.change))}
                      {c.change_pct !== null && <span className="text-slate-500"> · {signedPct(c.change_pct)}</span>}
                    </span>
                  ) : (
                    <span className="text-slate-600 shrink-0">no data yet</span>
                  )}
                </div>
              ))}
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-slate-300">Owed on credit</span>
              <span className="tnum text-warn shrink-0">{gbp(Number(summary.credit_owed))}</span>
            </div>
          </SummaryCard>
        </div>
      )}
    </div>
  )
}
