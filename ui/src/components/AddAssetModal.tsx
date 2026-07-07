import { useState } from 'react'
import { assetsAPI } from '../services/api'
import { ASSET_TYPE_LABEL, ASSET_TYPES, LIABILITY_TYPES, isLiabilityType } from '../lib/assets'

export default function AddAssetModal({
  onClose,
  onSaved,
  liability = false,
}: {
  onClose: () => void
  onSaved: () => void
  /** Start on a liability type (opened from "Add a liability"). */
  liability?: boolean
}) {
  const [name, setName] = useState('')
  const [assetType, setAssetType] = useState(liability ? 'mortgage' : 'isa')
  const [value, setValue] = useState('')
  const [valuedAt, setValuedAt] = useState('')
  const [saving, setSaving] = useState(false)

  const isLiab = isLiabilityType(assetType)

  const save = async () => {
    if (!name.trim() || value === '') return
    setSaving(true)
    await assetsAPI.create({
      name,
      asset_type: assetType,
      // Liabilities are stored as a negative valuation (amount owed).
      value: isLiab ? -Math.abs(Number(value)) : Number(value),
      valued_at: valuedAt || undefined,
    })
    onSaved()
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-4">
          {isLiab ? 'Add liability' : 'Add asset'}
        </h3>
        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={isLiab ? 'Name (e.g. Flat mortgage)' : 'Name (e.g. Vanguard S&S ISA)'}
            className="input"
            autoFocus
          />
          <select value={assetType} onChange={(e) => setAssetType(e.target.value)} className="input">
            <optgroup label="Assets">
              {ASSET_TYPES.map((k) => (
                <option key={k} value={k}>{ASSET_TYPE_LABEL[k]}</option>
              ))}
            </optgroup>
            <optgroup label="Liabilities">
              {[...LIABILITY_TYPES].map((k) => (
                <option key={k} value={k}>{ASSET_TYPE_LABEL[k]}</option>
              ))}
            </optgroup>
          </select>
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={isLiab ? 'Amount owed (£)' : 'Current value (£)'}
            className="input"
          />
          <div>
            <label className="label">
              {isLiab ? 'Balance as of' : 'Valued as of'} (optional, defaults to today)
            </label>
            <input type="date" value={valuedAt} onChange={(e) => setValuedAt(e.target.value)} className="input" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving || !name.trim() || value === ''} className="btn-primary">
            {saving ? 'Saving…' : isLiab ? 'Add liability' : 'Add asset'}
          </button>
        </div>
      </div>
    </div>
  )
}
