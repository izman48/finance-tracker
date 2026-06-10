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

const ASSET_TYPE_LABEL: Record<string, string> = {
  isa: 'ISA',
  savings: 'Savings',
  investment: 'Investments',
  pension: 'Pension',
  property: 'Property',
  crypto: 'Crypto',
  other: 'Other',
}

const RANGES = [
  { months: 6, label: '6m' },
  { months: 12, label: '1y' },
  { months: 24, label: '2y' },
  { months: 60, label: '5y' },
]

const gbp = (n: number) =>
  new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 0 }).format(n)

const latestValue = (a: Asset) =>
  a.valuations.length ? Number(a.valuations[a.valuations.length - 1].value) : 0

export default function NetWorthPage() {
  const [history, setHistory] = useState<NetWorthPoint[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [summary, setSummary] = useState<any | null>(null)
  const [months, setMonths] = useState(12)
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [updating, setUpdating] = useState<Asset | null>(null)

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
    if (!confirm(`Delete "${asset.name}" and its value history?`)) return
    await assetsAPI.remove(asset.id)
    await load()
  }

  if (loading) {
    return <div className="max-w-5xl mx-auto px-4 py-8 text-center text-gray-600">Calculating net worth…</div>
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
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-6">
        <h1 className="text-2xl sm:text-3xl font-bold">Net worth</h1>
        <button
          onClick={() => setShowAdd(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Add asset
        </button>
      </div>

      {/* Headline */}
      <div className="mb-6 p-6 bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="text-sm text-gray-500 mb-1">Total net worth</div>
        <div className="text-4xl sm:text-5xl font-bold text-gray-900">{gbp(current)}</div>
        <div className={`text-sm mt-1 ${change >= 0 ? 'text-green-600' : 'text-red-600'}`}>
          {change >= 0 ? '+' : ''}{gbp(change)} over the period
        </div>
        {summary && (
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-2 text-sm">
            <div className="flex justify-between border-t pt-2">
              <span className="text-gray-600">Cash</span>
              <span className="font-semibold">{gbp(Number(summary.available_cash))}</span>
            </div>
            <div className="flex justify-between border-t pt-2">
              <span className="text-gray-600">Savings accounts</span>
              <span className="font-semibold">{gbp(Number(summary.savings_total ?? 0))}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Other assets</span>
              <span className="font-semibold">{gbp(Number(summary.assets_total ?? 0))}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-600">Credit owed</span>
              <span className="font-semibold text-red-600">−{gbp(Number(summary.credit_owed))}</span>
            </div>
          </div>
        )}
      </div>

      {/* History chart */}
      <div className="mb-6 p-4 sm:p-6 bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Over time</h2>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r.months}
                onClick={() => changeRange(r.months)}
                className={`px-3 py-1 text-sm rounded-lg ${
                  months === r.months ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
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
                <stop offset="5%" stopColor="#2563eb" stopOpacity={0.25} />
                <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="date" fontSize={12} />
            <YAxis tickFormatter={(v) => gbp(v)} width={70} fontSize={12} />
            <Tooltip formatter={(v) => gbp(Number(v))} />
            <Area type="monotone" dataKey="Net worth" stroke="#2563eb" strokeWidth={2} fill="url(#nw)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Manual assets */}
      <h2 className="text-xl font-semibold mb-3">Your assets</h2>
      {assets.length === 0 ? (
        <div className="p-8 bg-white rounded-xl shadow-sm text-center text-gray-500">
          Track things your bank doesn't know about — ISAs, pensions, property, crypto.
          They'll be included in your net worth above.
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {assets.map((asset) => (
            <div key={asset.id} className="p-5 bg-white rounded-xl shadow-sm border border-gray-200">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h3 className="font-semibold">{asset.name}</h3>
                  <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
                    {ASSET_TYPE_LABEL[asset.asset_type] ?? asset.asset_type}
                  </span>
                </div>
              </div>
              <p className="text-2xl font-bold">{gbp(latestValue(asset))}</p>
              {asset.valuations.length > 1 && (
                <p className="text-xs text-gray-500 mt-1">
                  {asset.valuations.length} valuations since{' '}
                  {new Date(asset.valuations[0].valued_at).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' })}
                </p>
              )}
              <div className="mt-3 flex gap-3 text-sm">
                <button onClick={() => setUpdating(asset)} className="text-blue-600 hover:text-blue-800">
                  Update value
                </button>
                <button onClick={() => removeAsset(asset)} className="text-gray-400 hover:text-red-600">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <AssetModal
          onClose={() => setShowAdd(false)}
          onSaved={async () => {
            setShowAdd(false)
            await load()
          }}
        />
      )}
      {updating && (
        <UpdateValueModal
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

function AssetModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('')
  const [assetType, setAssetType] = useState('isa')
  const [value, setValue] = useState('')
  const [valuedAt, setValuedAt] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!name.trim() || value === '') return
    setSaving(true)
    await assetsAPI.create({
      name,
      asset_type: assetType,
      value: Number(value),
      valued_at: valuedAt || undefined,
    })
    onSaved()
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-4">Add asset</h3>
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. Vanguard S&S ISA)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            autoFocus
          />
          <select
            value={assetType}
            onChange={(e) => setAssetType(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          >
            {Object.entries(ASSET_TYPE_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Current value (£)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          />
          <div>
            <label className="block text-sm text-gray-600 mb-1">Valued as of (optional, defaults to today)</label>
            <input
              type="date"
              value={valuedAt}
              onChange={(e) => setValuedAt(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={save}
            disabled={saving || !name.trim() || value === ''}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Add asset'}
          </button>
        </div>
      </div>
    </div>
  )
}

function UpdateValueModal({ asset, onClose, onSaved }: { asset: Asset; onClose: () => void; onSaved: () => void }) {
  const [value, setValue] = useState(String(latestValue(asset)))
  const [valuedAt, setValuedAt] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (value === '') return
    setSaving(true)
    await assetsAPI.addValuation(asset.id, { value: Number(value), valued_at: valuedAt || undefined })
    onSaved()
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">{asset.name}</h3>
        <p className="text-sm text-gray-500 mb-4">
          Record its value — past entries stay, building the history behind the chart.
        </p>
        <div className="space-y-3">
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Value (£)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            autoFocus
          />
          <div>
            <label className="block text-sm text-gray-600 mb-1">As of (optional, defaults to today)</label>
            <input
              type="date"
              value={valuedAt}
              onChange={(e) => setValuedAt(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            />
          </div>
          {asset.valuations.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-3 text-xs text-gray-500 max-h-28 overflow-y-auto">
              {[...asset.valuations].reverse().map((v) => (
                <div key={v.id} className="flex justify-between py-0.5">
                  <span>{new Date(v.valued_at).toLocaleDateString('en-GB')}</span>
                  <span>{gbp(Number(v.value))}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={save}
            disabled={saving || value === ''}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save value'}
          </button>
        </div>
      </div>
    </div>
  )
}
