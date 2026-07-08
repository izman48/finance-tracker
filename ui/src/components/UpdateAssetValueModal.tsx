import { useState } from 'react'
import { assetsAPI, Asset } from '../services/api'
import { latestValue, isLiabilityType } from '../lib/assets'
import { gbp0 as gbp } from '../lib/format'

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
  // Liabilities are shown/entered as a positive "owed" figure, stored negative.
  const [value, setValue] = useState(String(Math.abs(latestValue(asset))))
  const [valuedAt, setValuedAt] = useState('')
  // Optional: money added (+) or withdrawn (−) since the last update. Recording
  // it lets the Wealth headline tell saving apart from growth.
  const [flow, setFlow] = useState('')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (value === '') return
    setSaving(true)
    const stored = isLiab ? -Math.abs(Number(value)) : Number(value)
    const flowAmount = Number(flow)
    if (flow !== '' && Number.isFinite(flowAmount) && flowAmount !== 0) {
      await assetsAPI.addFlow(asset.id, { amount: flowAmount, flow_date: valuedAt || undefined })
    }
    await assetsAPI.addValuation(asset.id, { value: stored, valued_at: valuedAt || undefined })
    onSaved()
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">{asset.name}</h3>
        <p className="text-sm text-slate-400 mb-4">
          Record its value — past entries stay, building the history behind the chart.
        </p>
        <div className="space-y-3">
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Value (£)"
            className="input"
            autoFocus
          />
          {!isLiab && (
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
          <div>
            <label className="label">As of (optional, defaults to today)</label>
            <input type="date" value={valuedAt} onChange={(e) => setValuedAt(e.target.value)} className="input" />
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
          <button onClick={save} disabled={saving || value === ''} className="btn-primary">
            {saving ? 'Saving…' : 'Save value'}
          </button>
        </div>
      </div>
    </div>
  )
}
