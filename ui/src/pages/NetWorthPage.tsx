import { useEffect, useState } from 'react'
import { Clock, Landmark, Plug, RefreshCw } from 'lucide-react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { assetsAPI, analyticsAPI, bankingAPI, Asset, AssetDecomposition, NetWorthPoint, Projection } from '../services/api'
import { BankStatus, CashflowSummary, SummaryAccount } from '../types'
import { ASSET_TYPE_LABEL, latestValue, isLiabilityType } from '../lib/assets'
import { gbp0 as gbp, timeAgo } from '../lib/format'
import AddAssetModal from '../components/AddAssetModal'
import UpdateAssetValueModal from '../components/UpdateAssetValueModal'
import AccountSettingsModal from '../components/AccountSettingsModal'
import AddToBalanceSheetChooser from '../components/AddToBalanceSheetChooser'
import AnimatedNumber from '../components/ui/AnimatedNumber'
import InfoTip from '../components/ui/InfoTip'
import { useConfirm } from '../components/ui/ConfirmDialog'
import { EXPLAIN } from '../copy/statExplainers'
import useReveal from '../components/ui/useReveal'

const RANGES = [
  { months: 6, label: '6m' },
  { months: 12, label: '1y' },
  { months: 24, label: '2y' },
  { months: 60, label: '5y' },
]

// The balance sheet: one grouped list of everything owned and owed.
const GROUPS = [
  { key: 'cash', label: 'Cash' },
  { key: 'savings', label: 'Savings' },
  { key: 'invest', label: 'Investments & pensions' },
  { key: 'property', label: 'Property' },
  { key: 'other', label: 'Other' },
  { key: 'owed', label: 'Owed' },
  { key: 'liabilities', label: 'Loans & mortgages' },
  { key: 'excluded', label: 'Excluded' },
] as const

const ROLE_GROUP: Record<string, string> = {
  spending: 'cash',
  savings: 'savings',
  credit: 'owed',
  excluded: 'excluded',
}

const ASSET_GROUP: Record<string, string> = {
  savings: 'savings',
  isa: 'invest',
  investment: 'invest',
  pension: 'invest',
  crypto: 'invest',
  property: 'property',
  other: 'other',
  mortgage: 'liabilities',
  loan: 'liabilities',
  other_liability: 'liabilities',
}

interface Row {
  key: string
  group: string
  name: string
  sub: string
  value: number
  live: boolean
  ageDays?: number
  onClick: () => void
}

function ageLabel(days: number) {
  if (days < 1) return 'today'
  if (days < 30) return `${Math.floor(days)}d old`
  if (days < 365) return `${Math.max(1, Math.round(days / 30.44))} mo old`
  return `${Math.max(1, Math.round(days / 365))} yr old`
}

function NetWorthTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-card2 border border-white/10 rounded-xl shadow-pop p-3 text-sm">
      <div className="font-medium text-slate-200">{label}</div>
      {payload.map((p: any) => (
        <div key={p.name} className="text-slate-300 tnum">
          {p.name}: {gbp(Number(p.value))}
        </div>
      ))}
    </div>
  )
}

export default function NetWorthPage() {
  const [history, setHistory] = useState<NetWorthPoint[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [summary, setSummary] = useState<CashflowSummary | null>(null)
  const [bankStatus, setBankStatus] = useState<BankStatus | null>(null)
  const [months, setMonths] = useState(12)
  const [loading, setLoading] = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState('')
  const [showChooser, setShowChooser] = useState(false)
  const [showAddAsset, setShowAddAsset] = useState(false)
  const [addLiability, setAddLiability] = useState(false)
  // Target & projection — v1 keeps the assumptions client-side (localStorage),
  // the backend just does the arithmetic. An estimate, not advice.
  const [target, setTarget] = useState(() => localStorage.getItem('wealth.target') ?? '')
  const [monthly, setMonthly] = useState(() => localStorage.getItem('wealth.monthly') ?? '')
  const [growth, setGrowth] = useState(() => localStorage.getItem('wealth.growth') ?? '5')
  // 'cashflow' derives the contribution from income − bills − avg spending
  // server-side; 'custom' sends the typed figure.
  const [contribMode, setContribMode] = useState<'cashflow' | 'custom'>(
    () => (localStorage.getItem('wealth.contribMode') === 'custom' ? 'custom' : 'cashflow'),
  )
  // Unticked = "all my future cashflow lands in my wealth": everyday spending
  // is measured and shown, but not subtracted (matches the Cashflow chart).
  const [subtractSpending, setSubtractSpending] = useState(
    () => localStorage.getItem('wealth.subtractSpending') !== '0',
  )
  const [showTargetForm, setShowTargetForm] = useState(false)
  const [projection, setProjection] = useState<Projection | null>(null)
  const [decomp, setDecomp] = useState<AssetDecomposition | null>(null)
  const [updating, setUpdating] = useState<Asset | null>(null)
  const [settingsAccount, setSettingsAccount] = useState<SummaryAccount | null>(null)
  const confirm = useConfirm()

  const revealRef = useReveal(!loading)

  const load = async (m = months) => {
    try {
      const [h, a, s, b, d] = await Promise.all([
        assetsAPI.netWorthHistory(m),
        assetsAPI.list(),
        analyticsAPI.getSummary(),
        bankingAPI.getConnectionStatus(),
        assetsAPI.decomposition(m),
      ])
      setHistory(h.data)
      setAssets(a.data)
      setSummary(s.data)
      setBankStatus(b.data)
      setDecomp(d.data)
    } catch (e) {
      console.error('Failed to load net worth', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const changeRange = async (m: number) => {
    setMonths(m)
    await load(m)
  }

  // Default the contribution from "savable" once the summary lands, unless the
  // user has already set their own figure.
  useEffect(() => {
    if (summary && !localStorage.getItem('wealth.monthly')) {
      setMonthly(String(Math.max(0, Math.round(Number(summary.savable)))))
    }
  }, [summary])

  // Fetch the projection when a target is set (debounced against typing).
  useEffect(() => {
    localStorage.setItem('wealth.target', target)
    localStorage.setItem('wealth.monthly', monthly)
    localStorage.setItem('wealth.growth', growth)
    localStorage.setItem('wealth.contribMode', contribMode)
    localStorage.setItem('wealth.subtractSpending', subtractSpending ? '1' : '0')
    const t = Number(target)
    if (!target || !Number.isFinite(t) || t <= 0) {
      setProjection(null)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      assetsAPI
        .netWorthProjection({
          target_amount: t,
          // Omitted in cashflow mode → the server derives it from income −
          // bills − average spending and returns the working.
          monthly_contribution: contribMode === 'custom' ? Number(monthly) || 0 : undefined,
          annual_growth_pct: Number(growth) || 0,
          subtract_spending: contribMode === 'cashflow' ? subtractSpending : undefined,
        })
        .then((res) => !cancelled && setProjection(res.data))
        .catch((e) => console.error('Failed to load projection', e))
    }, 500)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [target, monthly, growth, contribMode, subtractSpending])

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

  const handleSync = async () => {
    setSyncing(true)
    setMessage('')
    try {
      await bankingAPI.syncAccounts()
      await bankingAPI.syncTransactions(1825)
      await load()
      setMessage('Accounts and transactions synced.')
    } catch (error: any) {
      setMessage('Failed to sync: ' + (error.response?.data?.detail || error.message))
    } finally {
      setSyncing(false)
    }
  }

  const handleDisconnectAll = async () => {
    const ok = await confirm({
      title: 'Disconnect all banks?',
      body: 'This deletes all accounts and transactions.',
      confirmLabel: 'Disconnect all',
      danger: true,
    })
    if (!ok) return
    try {
      const response = await bankingAPI.disconnectAllBanks()
      setMessage(response.data.message)
      await load()
    } catch (error: any) {
      setMessage('Failed to disconnect: ' + (error.response?.data?.detail || error.message))
    }
  }

  const deleteAsset = async (asset: Asset) => {
    const ok = await confirm({
      title: `Delete "${asset.name}"?`,
      body: 'Its value history goes with it.',
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    await assetsAPI.remove(asset.id)
    setUpdating(null)
    await load()
  }

  if (loading) {
    return <div className="max-w-5xl mx-auto px-4 py-8 text-center text-slate-500">Calculating net worth…</div>
  }

  const current = history.length ? Number(history[history.length - 1].net_worth) : 0
  const first = history.length ? Number(history[0].net_worth) : 0
  const change = current - first
  const monthLabel = (d: string) =>
    new Date(d).toLocaleDateString('en-GB', { month: 'short', year: '2-digit' })
  const historyRows = history.map((p) => ({
    date: monthLabel(p.date),
    'Net worth': Number(p.net_worth),
    Banks: Number(p.bank),
    Assets: Number(p.assets),
  }))
  // The dashed estimate extends the solid line: the junction row carries both
  // keys so the two areas connect, then projection-only rows follow.
  const projRows =
    projection && historyRows.length
      ? projection.timeline.slice(1).map((p) => ({ date: monthLabel(p.date), Projected: Number(p.value) }))
      : []
  const chartData = projRows.length
    ? [
        ...historyRows.map((r, i) => (i === historyRows.length - 1 ? { ...r, Projected: current } : r)),
        ...projRows,
      ]
    : historyRows
  const targetNum = Number(target) > 0 ? Number(target) : null
  const targetMonthYear = projection?.target_date
    ? new Date(projection.target_date).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
    : null

  // Assemble the balance sheet: bank accounts (live) + manual assets, grouped.
  const now = Date.now()
  const rows: Row[] = []
  for (const account of summary?.accounts ?? []) {
    const balance = Number(account.current_balance ?? 0)
    rows.push({
      key: `acc-${account.id}`,
      group: ROLE_GROUP[account.role] ?? 'other',
      name: account.display_name,
      sub: account.provider_name,
      value: account.role === 'credit' ? -Math.abs(balance) : balance,
      live: true,
      onClick: () => setSettingsAccount(account),
    })
  }
  for (const asset of assets) {
    const value = latestValue(asset)
    const last = asset.valuations[asset.valuations.length - 1]
    const ageDays = last ? (now - new Date(last.valued_at).getTime()) / 86400000 : undefined
    rows.push({
      key: `asset-${asset.id}`,
      group: isLiabilityType(asset.asset_type)
        ? 'liabilities'
        : value < 0
          ? 'owed'
          : ASSET_GROUP[asset.asset_type] ?? 'other',
      name: asset.name,
      sub: ASSET_TYPE_LABEL[asset.asset_type] ?? asset.asset_type,
      value,
      live: false,
      ageDays,
      onClick: () => setUpdating(asset),
    })
  }

  const providers = Array.from(new Set((bankStatus?.connections ?? []).map((c) => c.provider_name)))
  const hasAnything = rows.length > 0

  return (
    <div ref={revealRef} className="max-w-5xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Wealth</h1>
        <button onClick={() => setShowChooser(true)} className="btn-primary">
          Add
        </button>
      </div>

      {message && (
        <div className={`mb-6 ${message.toLowerCase().includes('failed') ? 'banner-err' : 'banner-ok'}`}>
          {message}
        </div>
      )}

      {/* Headline */}
      <div className="card p-6 sm:p-8 mb-6 relative overflow-hidden" data-reveal>
        <div className="orb w-72 h-72 bg-sky2/10 -top-24 -right-16" />
        <div className="relative">
          <div className="text-sm text-slate-400 mb-2 flex items-center gap-1.5">
            Total net worth
            <InfoTip text={EXPLAIN.netWorth} side="bottom" align="left" />
          </div>
          <div className="stat-figure text-5xl sm:text-6xl text-slate-50">
            <AnimatedNumber value={current} format={gbp} />
          </div>
          <div className={`text-sm mt-2 tnum flex items-center gap-1.5 ${change >= 0 ? 'text-pos' : 'text-neg'}`}>
            {change >= 0 ? '+' : ''}{gbp(change)} over the period
            <InfoTip text={EXPLAIN.netWorthChange} side="bottom" align="left" />
          </div>
          {decomp && Number(decomp.assets_delta) !== 0 && (
            <div className="text-xs text-slate-500 mt-1.5 tnum flex items-center gap-1.5 flex-wrap">
              {decomp.flows_recorded > 0 ? (
                <>
                  Assets {Number(decomp.assets_delta) >= 0 ? '+' : '−'}{gbp(Math.abs(Number(decomp.assets_delta)))} —{' '}
                  {gbp(Math.abs(Number(decomp.contributions)))} {Number(decomp.contributions) >= 0 ? 'added' : 'withdrawn'}{' '}
                  · {Number(decomp.growth) >= 0 ? '+' : '−'}{gbp(Math.abs(Number(decomp.growth)))} growth
                  <InfoTip
                    text="Growth = the change in your manually tracked assets minus the deposits and withdrawals you've recorded. Anything you didn't record shows up as growth. Bank balances aren't part of this split — the ledger already explains those."
                    side="bottom"
                    align="left"
                  />
                </>
              ) : (
                <>
                  Assets {Number(decomp.assets_delta) >= 0 ? '+' : '−'}{gbp(Math.abs(Number(decomp.assets_delta)))} over the period —
                  record deposits and withdrawals when you update a value to split saving from growth.
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* History chart + forward projection */}
      <div className="card-pad mb-6" data-reveal>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <h2 className="font-display font-semibold text-slate-100">Over time</h2>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setShowTargetForm((s) => !s)}
              className={`seg ${showTargetForm || targetNum ? '!text-accent' : ''}`}
            >
              {targetNum ? `Target ${gbp(targetNum)}` : 'Set a target'}
            </button>
            <div className="flex gap-0.5">
              {RANGES.map((r) => (
                <button
                  key={r.months}
                  onClick={() => changeRange(r.months)}
                  className={months === r.months ? 'seg-active' : 'seg'}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {showTargetForm && (
          <div className="flex flex-wrap items-end gap-3 mb-4">
            <div>
              <label className="label">Target (£)</label>
              <input type="number" min="0" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="e.g. 250000" className="input !w-36" />
            </div>
            <div>
              <label className="label">Adding monthly</label>
              <div className="flex items-center gap-0.5">
                <button
                  onClick={() => setContribMode('cashflow')}
                  className={contribMode === 'cashflow' ? 'seg-active' : 'seg'}
                  title="Derived from your confirmed income and bills minus your average everyday spending"
                >
                  From my cashflow
                </button>
                <button
                  onClick={() => setContribMode('custom')}
                  className={contribMode === 'custom' ? 'seg-active' : 'seg'}
                >
                  Custom
                </button>
                {contribMode === 'custom' && (
                  <input
                    type="number"
                    step="10"
                    value={monthly}
                    onChange={(e) => setMonthly(e.target.value)}
                    placeholder="£/mo"
                    className="input !w-28 ml-2"
                  />
                )}
              </div>
            </div>
            <div>
              <label className="label">Growth %/yr</label>
              <input type="number" step="0.5" value={growth} onChange={(e) => setGrowth(e.target.value)} className="input !w-24" />
            </div>
            {target && (
              <button onClick={() => setTarget('')} className="btn-ghost !py-2">
                Clear target
              </button>
            )}
            {contribMode === 'cashflow' && (
              <label className="basis-full flex items-start sm:items-center cursor-pointer -mt-1">
                <input
                  type="checkbox"
                  checked={subtractSpending}
                  onChange={(e) => setSubtractSpending(e.target.checked)}
                  className="checkbox mt-0.5 sm:mt-0"
                />
                <span className="ml-2 text-sm text-slate-300">
                  Subtract my average everyday spending
                  <span className="ml-1 text-xs text-slate-500">
                    (untick to assume all your forecasted cashflow lands in your wealth, like the Cashflow chart)
                  </span>
                </span>
              </label>
            )}
          </div>
        )}

        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="nw" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#38BDF8" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#38BDF8" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" fontSize={12} tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis tickFormatter={(v) => gbp(v)} width={70} fontSize={12} tickLine={false} axisLine={false} />
            <Tooltip content={<NetWorthTooltip />} />
            {targetNum && projRows.length > 0 && (
              <ReferenceLine
                y={targetNum}
                stroke="#2DD4A7"
                strokeDasharray="4 4"
                label={{ value: 'target', position: 'insideTopRight', fontSize: 11, fill: '#2DD4A7' }}
              />
            )}
            <Area type="monotone" dataKey="Net worth" stroke="#38BDF8" strokeWidth={2} fill="url(#nw)" />
            {projRows.length > 0 && (
              <Area
                type="monotone"
                dataKey="Projected"
                stroke="#2DD4A7"
                strokeWidth={2}
                strokeDasharray="6 4"
                fill="none"
                fillOpacity={0}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>

        {projection && targetNum && (
          <p className="text-xs text-slate-500 mt-3">
            {targetMonthYear ? (
              <>
                On these assumptions you'd reach <span className="text-slate-300 tnum">{gbp(targetNum)}</span> around{' '}
                <span className="text-accent">{targetMonthYear}</span>.
              </>
            ) : (
              <>Not reached within 50 years on these assumptions.</>
            )}{' '}
            Your monthly surplus of{' '}
            <span className="tnum">~{gbp(Number(projection.monthly_contribution))}/mo</span>
            {projection.contribution_basis ? (
              projection.contribution_basis.spending_subtracted ? (
                <>
                  {' '}(from your cashflow:{' '}
                  <span className="tnum">
                    {gbp(Number(projection.contribution_basis.income_monthly))} income −{' '}
                    {gbp(Number(projection.contribution_basis.bills_monthly))} bills −{' '}
                    {gbp(Number(projection.contribution_basis.avg_spending_monthly))} avg spending
                  </span>
                  , month by month like the Cashflow forecast)
                </>
              ) : (
                <>
                  {' '}(all of your forecasted cashflow:{' '}
                  <span className="tnum">
                    {gbp(Number(projection.contribution_basis.income_monthly))} income −{' '}
                    {gbp(Number(projection.contribution_basis.bills_monthly))} bills
                  </span>
                  ; your measured{' '}
                  <span className="tnum">{gbp(Number(projection.contribution_basis.avg_spending_monthly))}/mo</span>{' '}
                  everyday spending is <span className="text-warn">not subtracted</span>)
                </>
              )
            ) : null}{' '}
            is swept into investments at {Number(projection.annual_growth_pct)}%/yr; your{' '}
            <span className="tnum">{gbp(Number(projection.bank_component))}</span> cash buffer stays as cash
            (negative months drain it first, never compounding as debt);
            each asset grows at its own assumed rate
            {(() => {
              const contribs = projection.asset_assumptions.filter((a) => Number(a.monthly_contribution) > 0)
              return contribs.length ? (
                <>
                  {' '}plus your planned{' '}
                  {contribs.map((a, i) => (
                    <span key={a.name}>
                      {i > 0 && ', '}
                      <span className="tnum">{gbp(Number(a.monthly_contribution))}/mo</span> into {a.name}
                    </span>
                  ))}
                </>
              ) : (
                <> (edit an asset to set its rate or a monthly contribution)</>
              )
            })()}
            . An estimate based on your {projection.contribution_basis ? 'data' : 'inputs'}, not advice.
          </p>
        )}

        {projection && targetNum && projection.contribution_basis && Number(projection.monthly_contribution) < 0 && (
          <p className="text-xs text-warn mt-2">
            Your measured spending exceeds income − bills, so this projection drifts down. If you
            move money between accounts or pay into investments monthly, those transfers can be
            counted as spending — declare them as planned contributions on the asset they go into
            (tap it in the balance sheet below), or review what's inside the figure on the
            Spending tab.
          </p>
        )}
      </div>

      {/* Balance sheet */}
      <h2 className="font-display font-semibold text-lg text-slate-100 mb-3" data-reveal>
        Your balance sheet
      </h2>
      {!hasAnything ? (
        <div className="card p-8 text-center text-slate-500 text-sm" data-reveal>
          Connect a bank for live balances, and add what your bank can't see — ISAs,
          pensions, property, crypto. Everything lands here, in one place.
          <div className="mt-4">
            <button onClick={() => setShowChooser(true)} className="btn-primary">
              Add to your balance sheet
            </button>
          </div>
        </div>
      ) : (
        <div className="card overflow-hidden mb-6" data-reveal>
          {GROUPS.map(({ key, label }) => {
            const groupRows = rows.filter((r) => r.group === key)
            if (groupRows.length === 0) return null
            const excluded = key === 'excluded'
            const subtotal = groupRows.reduce((s, r) => s + r.value, 0)
            return (
              <div key={key}>
                <div className="px-4 pt-4 pb-1.5 flex items-baseline justify-between">
                  <span className="text-xs uppercase tracking-wider text-slate-500">
                    {label}
                    {excluded && (
                      <span className="ml-2 normal-case tracking-normal">not counted in net worth</span>
                    )}
                  </span>
                  {!excluded && (
                    <span className={`text-sm tnum ${subtotal < 0 ? 'text-warn' : 'text-slate-400'}`}>
                      {subtotal < 0 ? '−' : ''}{gbp(Math.abs(subtotal))}
                    </span>
                  )}
                </div>
                {groupRows.map((row) => (
                  <button
                    key={row.key}
                    onClick={row.onClick}
                    className="w-full flex items-center gap-3 px-4 py-3 border-t border-white/[0.06] text-left hover:bg-white/[0.03] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
                  >
                    <span className="min-w-0 flex-1">
                      <span className={`block text-sm font-medium truncate ${excluded ? 'text-slate-500' : 'text-slate-100'}`}>
                        {row.name}
                      </span>
                      <span className="block text-xs text-slate-500 truncate">{row.sub}</span>
                    </span>
                    {row.live ? (
                      <span className="chip shrink-0" title={EXPLAIN.liveBalance}>live</span>
                    ) : row.ageDays !== undefined ? (
                      <span
                        className={`${row.ageDays > 180 ? 'chip-warn' : 'chip'} shrink-0 inline-flex items-center gap-1`}
                        title={EXPLAIN.assetAge}
                      >
                        <Clock className="w-3 h-3" />
                        {ageLabel(row.ageDays)}
                      </span>
                    ) : null}
                    <span
                      className={`shrink-0 text-sm font-semibold tnum ${
                        excluded ? 'text-slate-600' : row.value < 0 ? 'text-warn' : 'text-slate-100'
                      }`}
                    >
                      {row.value < 0 ? '−' : ''}{gbp(Math.abs(row.value))}
                    </span>
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      )}

      {/* Connections management */}
      <div className="mb-8" data-reveal>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <div>
            <h2 className="font-display font-semibold text-lg text-slate-100">Connected banks</h2>
            {bankStatus?.last_synced_at && (
              <p className="text-sm text-slate-500">
                Synced {timeAgo(bankStatus.last_synced_at)} · syncs at every login
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" onClick={handleConnectBank} disabled={connecting}>
              <Plug className="w-4 h-4" />
              {connecting ? 'Connecting…' : providers.length > 0 ? 'Connect another bank' : 'Connect a bank'}
            </button>
            {bankStatus?.is_connected && (
              <>
                <button className="btn-ghost" onClick={handleSync} disabled={syncing}>
                  <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
                  {syncing ? 'Syncing…' : 'Sync all'}
                </button>
                <button className="btn-danger" onClick={handleDisconnectAll} disabled={connecting || syncing}>
                  Disconnect all
                </button>
              </>
            )}
          </div>
        </div>

        {bankStatus?.connections && bankStatus.connections.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {bankStatus.connections.map((conn) => (
              <div key={conn.id} className="card p-5 flex items-center gap-3">
                <span className="w-10 h-10 rounded-xl bg-white/[0.06] flex items-center justify-center">
                  <Landmark className="w-5 h-5 text-slate-400" />
                </span>
                <div>
                  <h3 className="font-semibold text-slate-100">{conn.provider_name}</h3>
                  <p className={`text-sm ${conn.is_expired ? 'text-neg' : 'text-pos'}`}>
                    {conn.is_expired ? 'Needs reconnection — connect it again above' : 'Active'}
                  </p>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="card p-8 text-center text-slate-500 text-sm">
            No banks connected yet — balances update automatically once you connect one.
          </div>
        )}
      </div>

      {showChooser && (
        <AddToBalanceSheetChooser
          providers={providers}
          onConnect={() => {
            setShowChooser(false)
            handleConnectBank()
          }}
          onManual={() => {
            setShowChooser(false)
            setAddLiability(false)
            setShowAddAsset(true)
          }}
          onLiability={() => {
            setShowChooser(false)
            setAddLiability(true)
            setShowAddAsset(true)
          }}
          onClose={() => setShowChooser(false)}
        />
      )}
      {showAddAsset && (
        <AddAssetModal
          liability={addLiability}
          onClose={() => setShowAddAsset(false)}
          onSaved={async () => {
            setShowAddAsset(false)
            await load()
          }}
        />
      )}
      {updating && (
        <UpdateAssetValueModal
          asset={updating}
          onClose={() => setUpdating(null)}
          onSaved={async () => {
            setUpdating(null)
            await load()
          }}
          onDelete={() => deleteAsset(updating)}
        />
      )}
      {settingsAccount && (
        <AccountSettingsModal
          account={settingsAccount}
          spendingAccounts={summary?.accounts.filter((a) => a.role === 'spending') ?? []}
          onClose={() => setSettingsAccount(null)}
          onSaved={async () => {
            setSettingsAccount(null)
            await load()
          }}
        />
      )}
    </div>
  )
}
