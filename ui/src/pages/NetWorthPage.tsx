import { useEffect, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { assetsAPI, analyticsAPI, Asset, NetWorthPoint } from '../services/api'
import { ASSET_TYPE_LABEL, latestValue } from '../lib/assets'
import { gbp0 as gbp } from '../lib/format'
import AddAssetModal from '../components/AddAssetModal'
import UpdateAssetValueModal from '../components/UpdateAssetValueModal'
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
  const [summary, setSummary] = useState<any | null>(null)
  const [months, setMonths] = useState(12)
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [updating, setUpdating] = useState<Asset | null>(null)
  const confirm = useConfirm()

  const revealRef = useReveal(!loading)

  const load = async (m = months) => {
    try {
      const [h, a, s] = await Promise.all([
        assetsAPI.netWorthHistory(m),
        assetsAPI.list(),
        analyticsAPI.getSummary(),
      ])
      setHistory(h.data)
      setAssets(a.data)
      setSummary(s.data)
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

  const removeAsset = async (asset: Asset) => {
    const ok = await confirm({
      title: `Delete "${asset.name}"?`,
      body: 'Its value history goes with it.',
      confirmLabel: 'Delete',
      danger: true,
    })
    if (!ok) return
    await assetsAPI.remove(asset.id)
    await load()
  }

  if (loading) {
    return <div className="max-w-5xl mx-auto px-4 py-8 text-center text-slate-500">Calculating net worth…</div>
  }

  const current = history.length ? Number(history[history.length - 1].net_worth) : 0
  const first = history.length ? Number(history[0].net_worth) : 0
  const change = current - first
  const chartData = history.map((p) => ({
    date: new Date(p.date).toLocaleDateString('en-GB', { month: 'short', year: '2-digit' }),
    'Net worth': Number(p.net_worth),
    Banks: Number(p.bank),
    Assets: Number(p.assets),
  }))

  return (
    <div ref={revealRef} className="max-w-5xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Wealth</h1>
        <button onClick={() => setShowAdd(true)} className="btn-primary">
          Add asset
        </button>
      </div>

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
          {summary && (
            <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
              {[
                { label: 'Cash', value: gbp(Number(summary.available_cash)), tone: 'text-slate-100', explain: EXPLAIN.availableCash },
                { label: 'Savings accounts', value: gbp(Number(summary.savings_total ?? 0)), tone: 'text-slate-100', explain: EXPLAIN.savingsTotal },
                { label: 'Other assets', value: gbp(Number(summary.assets_total ?? 0)), tone: 'text-slate-100', explain: EXPLAIN.assetsTotal },
                { label: 'Credit owed', value: `−${gbp(Number(summary.credit_owed))}`, tone: 'text-neg', explain: EXPLAIN.creditOwed },
              ].map((s) => (
                <div key={s.label}>
                  <div className="text-xs text-slate-500 mb-1 flex items-center gap-1.5">
                    {s.label}
                    <InfoTip text={s.explain} align="left" />
                  </div>
                  <div className={`font-semibold tnum ${s.tone}`}>{s.value}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* History chart */}
      <div className="card-pad mb-6" data-reveal>
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display font-semibold text-slate-100">Over time</h2>
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
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={chartData}>
            <defs>
              <linearGradient id="nw" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#38BDF8" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#38BDF8" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis tickFormatter={(v) => gbp(v)} width={70} fontSize={12} tickLine={false} axisLine={false} />
            <Tooltip content={<NetWorthTooltip />} />
            <Area type="monotone" dataKey="Net worth" stroke="#38BDF8" strokeWidth={2} fill="url(#nw)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Manual assets */}
      <h2 className="font-display font-semibold text-lg text-slate-100 mb-3" data-reveal>
        Your assets
      </h2>
      {assets.length === 0 ? (
        <div className="card p-8 text-center text-slate-500 text-sm" data-reveal>
          Track things your bank doesn't know about — ISAs, pensions, property, crypto.
          They'll be included in your net worth above.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-reveal>
          {assets.map((asset) => (
            <div key={asset.id} className="card p-5">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h3 className="font-semibold text-slate-100">{asset.name}</h3>
                  <span className="chip-info mt-1">
                    {ASSET_TYPE_LABEL[asset.asset_type] ?? asset.asset_type}
                  </span>
                </div>
              </div>
              <p className="stat-figure text-2xl text-slate-50">{gbp(latestValue(asset))}</p>
              {asset.valuations.length > 1 && (
                <p className="text-xs text-slate-500 mt-1">
                  {asset.valuations.length} valuations since{' '}
                  {new Date(asset.valuations[0].valued_at).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}
                </p>
              )}
              <div className="mt-3 flex gap-4 text-sm">
                <button onClick={() => setUpdating(asset)} className="btn-link">
                  Update value
                </button>
                <button onClick={() => removeAsset(asset)} className="text-slate-500 hover:text-neg transition-colors">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <AddAssetModal
          onClose={() => setShowAdd(false)}
          onSaved={async () => {
            setShowAdd(false)
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
        />
      )}
    </div>
  )
}
