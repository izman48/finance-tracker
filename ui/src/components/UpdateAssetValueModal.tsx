import { useEffect, useRef, useState } from 'react'
import { assetsAPI, Asset, InstrumentSearchResult } from '../services/api'
import { latestValue, isLiabilityType } from '../lib/assets'
import { gbp0 as gbp } from '../lib/format'
import { useToast } from './ui/Toast'

export default function UpdateAssetValueModal({
  asset,
  onClose,
  onSaved,
  onDelete,
}: {
  asset: Asset
  onClose: () => void
  onSaved: () => void
  onDelete?: () => void
}) {
  const isLiab = isLiabilityType(asset.asset_type)
  const linked = !!asset.instrument
  const showToast = useToast()
  // Liabilities are shown/entered as a positive "owed" figure, stored negative.
  const [value, setValue] = useState(String(Math.abs(latestValue(asset))))
  const [valuedAt, setValuedAt] = useState('')
  // Optional: money added (+) or withdrawn (−) since the last update. Recording
  // it lets the Wealth headline tell saving apart from growth.
  const [flow, setFlow] = useState('')
  // Projection assumption: %/yr this asset is assumed to grow. Empty → the
  // projection's default (global rate for assets, flat for liabilities).
  const [growth, setGrowth] = useState(asset.assumed_growth_pct ?? '')
  // Planned monthly saving into this asset (paydown for a liability). The
  // projection adds it to the asset each month.
  const [contribution, setContribution] = useState(asset.monthly_contribution ?? '')
  const [saving, setSaving] = useState(false)

  // --- live pricing: search + link ---------------------------------------- #
  const [showLink, setShowLink] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<InstrumentSearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<InstrumentSearchResult | null>(null)
  const [units, setUnits] = useState(asset.units ?? '')
  const [linking, setLinking] = useState(false)
  const searchTimer = useRef<ReturnType<typeof setTimeout>>()

  useEffect(() => {
    clearTimeout(searchTimer.current)
    if (query.trim().length < 2) {
      setResults([])
      return
    }
    setSearching(true)
    searchTimer.current = setTimeout(() => {
      assetsAPI
        .searchInstruments(query.trim())
        .then((r) => setResults(r.data))
        .catch(() => setResults([]))
        .finally(() => setSearching(false))
    }, 400)
    return () => clearTimeout(searchTimer.current)
  }, [query])

  const link = async () => {
    if (!selected || !units || Number(units) <= 0) return
    setLinking(true)
    try {
      await assetsAPI.linkInstrument(asset.id, { instrument_id: selected.id, units: Number(units) })
      onSaved()
    } catch {
      showToast('Could not link — try again', { tone: 'err' })
      setLinking(false)
    }
  }

  const unlink = async () => {
    setLinking(true)
    try {
      await assetsAPI.unlinkInstrument(asset.id)
      onSaved()
    } catch {
      showToast('Could not unlink', { tone: 'err' })
      setLinking(false)
    }
  }

  const save = async () => {
    if (!linked && value === '') return
    setSaving(true)
    const flowAmount = Number(flow)
    if (!linked && flow !== '' && Number.isFinite(flowAmount) && flowAmount !== 0) {
      await assetsAPI.addFlow(asset.id, { amount: flowAmount, flow_date: valuedAt || undefined })
    }
    const patch: { assumed_growth_pct?: number | null; monthly_contribution?: number | null } = {}
    if (String(growth) !== String(asset.assumed_growth_pct ?? '')) {
      patch.assumed_growth_pct = growth === '' ? null : Number(growth)
    }
    if (String(contribution) !== String(asset.monthly_contribution ?? '')) {
      patch.monthly_contribution = contribution === '' ? null : Math.abs(Number(contribution))
    }
    if (Object.keys(patch).length) {
      await assetsAPI.update(asset.id, patch)
    }
    // A priced asset's value comes from the market — don't overwrite it.
    if (!linked) {
      const stored = isLiab ? -Math.abs(Number(value)) : Number(value)
      await assetsAPI.addValuation(asset.id, { value: stored, valued_at: valuedAt || undefined })
    }
    onSaved()
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">{asset.name}</h3>
        <p className="text-sm text-slate-400 mb-4">
          {linked
            ? 'This holding is priced live — its value updates from the market each time you open Wealth.'
            : 'Record its value — past entries stay, building the history behind the chart.'}
        </p>
        <div className="space-y-3">
          {linked ? (
            <div className="rounded-xl border border-accent/25 bg-accent/[0.06] p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm text-slate-200">
                  <span className="chip mr-1.5">live</span>
                  {Number(asset.units)} {asset.instrument!.symbol}
                  {asset.unit_price_gbp != null && (
                    <span className="text-slate-400"> · {gbp(Number(asset.unit_price_gbp))} each</span>
                  )}
                </span>
                <span className="font-semibold tnum text-slate-100">{gbp(Math.abs(latestValue(asset)))}</span>
              </div>
              <button onClick={unlink} disabled={linking} className="mt-2 text-xs text-slate-500 hover:text-neg transition-colors">
                {linking ? 'Unlinking…' : 'Unlink — go back to manual values'}
              </button>
            </div>
          ) : (
            <input
              type="number"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Value (£)"
              className="input"
              autoFocus
            />
          )}

          {!isLiab && !linked && (
            <div>
              <label className="label">
                Added or withdrew since last update (£, optional — use − for withdrawals)
              </label>
              <input
                type="number"
                step="0.01"
                value={flow}
                onChange={(e) => setFlow(e.target.value)}
                placeholder="e.g. 500 added, -200 withdrawn"
                className="input"
              />
              <p className="text-xs text-slate-500 mt-1">
                Recording this lets Wealth split your change into saving vs growth.
              </p>
            </div>
          )}

          {!linked && (
            <div>
              <label className="label">As of (optional, defaults to today)</label>
              <input type="date" value={valuedAt} onChange={(e) => setValuedAt(e.target.value)} className="input" />
            </div>
          )}

          {/* Live pricing — only for asset-side holdings (not liabilities). */}
          {!isLiab && !linked && (
            <div>
              {!showLink ? (
                <button onClick={() => setShowLink(true)} className="text-sm text-accent hover:underline">
                  Price it live from the market →
                </button>
              ) : (
                <div className="rounded-xl border border-white/10 p-3 space-y-2">
                  <label className="label">Link a live price (crypto, stocks, ETFs)</label>
                  <input
                    value={query}
                    onChange={(e) => { setQuery(e.target.value); setSelected(null) }}
                    placeholder="Search e.g. bitcoin, AAPL, VUSA"
                    className="input"
                    autoFocus
                  />
                  {searching && <p className="text-xs text-slate-500">Searching…</p>}
                  {!selected && results.length > 0 && (
                    <div className="border border-white/10 rounded-lg max-h-40 overflow-y-auto divide-y divide-white/[0.06]">
                      {results.map((r) => (
                        <button
                          key={r.id}
                          onClick={() => { setSelected(r); setResults([]); setQuery(`${r.symbol} — ${r.name}`) }}
                          className="w-full text-left px-3 py-2 hover:bg-white/[0.04] transition-colors"
                        >
                          <span className="text-sm text-slate-200 font-medium">{r.symbol}</span>
                          <span className="text-xs text-slate-500 ml-2">{r.name}</span>
                          <span className="text-[10px] uppercase tracking-wide text-slate-600 ml-2">{r.kind}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {selected && (
                    <div className="flex items-end gap-2">
                      <div className="flex-1">
                        <label className="label">Units of {selected.symbol} held</label>
                        <input
                          type="number"
                          step="any"
                          min="0"
                          value={units}
                          onChange={(e) => setUnits(e.target.value)}
                          placeholder="e.g. 0.5"
                          className="input"
                        />
                      </div>
                      <button onClick={link} disabled={linking || !units || Number(units) <= 0} className="btn-primary">
                        {linking ? 'Linking…' : 'Link'}
                      </button>
                    </div>
                  )}
                  <p className="text-xs text-slate-500">
                    Crypto works out of the box; stocks/ETFs need a market-data key on the server.
                  </p>
                </div>
              )}
            </div>
          )}

          <div>
            <label className="label">
              Assumed growth %/yr for projections (optional{isLiab ? ', liabilities default to flat' : ''})
            </label>
            <input
              type="number"
              step="0.5"
              value={growth}
              onChange={(e) => setGrowth(e.target.value)}
              placeholder={isLiab ? 'e.g. -8 as you pay it down' : 'blank = your global growth rate'}
              className="input"
            />
          </div>
          <div>
            <label className="label">
              {isLiab ? 'Planned monthly payment against it (£/mo, optional)' : 'Planned monthly contribution (£/mo, optional)'}
            </label>
            <input
              type="number"
              min="0"
              step="10"
              value={contribution}
              onChange={(e) => setContribution(e.target.value)}
              placeholder={isLiab ? 'e.g. 200 — projections shrink it to £0' : 'e.g. 500 — your ISA direct debit'}
              className="input"
            />
            <p className="text-xs text-slate-500 mt-1">
              {isLiab
                ? 'Projections pay it down monthly and stop at zero.'
                : "Money you send here usually shows up as 'spending' — declaring it moves it into your wealth projection instead."}
            </p>
          </div>
          {asset.valuations.length > 0 && (
            <div className="bg-white/[0.04] border border-white/[0.06] rounded-xl p-3 text-xs text-slate-500 max-h-28 overflow-y-auto">
              {[...asset.valuations].reverse().map((v) => (
                <div key={v.id} className="flex justify-between py-0.5 tnum">
                  <span>{new Date(v.valued_at).toLocaleDateString('en-GB')}</span>
                  <span>{gbp(Number(v.value))}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 mt-5">
          {onDelete && (
            <button
              onClick={onDelete}
              className="text-sm text-slate-500 hover:text-neg transition-colors mr-auto"
            >
              Delete asset
            </button>
          )}
          <button onClick={onClose} className={`btn-ghost ${onDelete ? '' : 'ml-auto'}`}>Cancel</button>
          <button onClick={save} disabled={saving || (!linked && value === '')} className="btn-primary">
            {saving ? 'Saving…' : linked ? 'Save' : 'Save value'}
          </button>
        </div>
      </div>
    </div>
  )
}
