import { useState } from 'react'
import { analyticsAPI } from '../services/api'
import { Transaction } from '../types'

export default function MakeRecurringModal({
  transaction,
  onClose,
  onDone,
}: {
  transaction: Transaction
  onClose: () => void
  onDone: (label: string) => void
}) {
  const [cadence, setCadence] = useState('monthly')
  const [saving, setSaving] = useState(false)
  const label = transaction.merchant_name || transaction.description || 'this transaction'

  const save = async () => {
    setSaving(true)
    try {
      await analyticsAPI.markTransactionRecurring(transaction.id, cadence)
      onDone(label)
    } catch (e) {
      console.error('Failed to mark recurring', e)
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel !max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">Mark as recurring</h3>
        <p className="text-sm text-slate-400 mb-4">
          Add <span className="font-medium text-slate-200">{label}</span> ({transaction.transaction_type === 'credit' ? 'income' : 'expense'}) as a
          confirmed commitment so it feeds your safe-to-spend and forecast.
        </p>
        <label className="label">How often?</label>
        <select value={cadence} onChange={(e) => setCadence(e.target.value)} className="input mb-5">
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="every_n_months">Every few months</option>
          <option value="yearly">Yearly</option>
        </select>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? 'Adding…' : 'Add to plan'}
          </button>
        </div>
      </div>
    </div>
  )
}
