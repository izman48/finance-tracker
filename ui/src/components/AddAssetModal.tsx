import { useState } from 'react'
import { assetsAPI } from '../services/api'
import { ASSET_TYPE_LABEL } from '../lib/assets'

export default function AddAssetModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
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
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-4">Add asset</h3>
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. Vanguard S&S ISA)"
            className="input"
            autoFocus
          />
          <select value={assetType} onChange={(e) => setAssetType(e.target.value)} className="input">
            {Object.entries(ASSET_TYPE_LABEL).map(([k, l]) => (
              <option key={k} value={k}>{l}</option>
            ))}
          </select>
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Current value (£)"
            className="input"
          />
          <div>
            <label className="label">Valued as of (optional, defaults to today)</label>
            <input type="date" value={valuedAt} onChange={(e) => setValuedAt(e.target.value)} className="input" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving || !name.trim() || value === ''} className="btn-primary">
            {saving ? 'Saving…' : 'Add asset'}
          </button>
        </div>
      </div>
    </div>
  )
}
