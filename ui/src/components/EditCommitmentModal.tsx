import { useState } from 'react'
import { analyticsAPI } from '../services/api'
import { Commitment } from '../types'
import { isYearly, merchantFromKey } from '../lib/cadence'

export default function EditCommitmentModal({
  commitment,
  onClose,
  onSaved,
}: {
  commitment: Commitment
  onClose: () => void
  onSaved: () => void
}) {
  const [label, setLabel] = useState(commitment.label)
  const [amount, setAmount] = useState(String(commitment.amount))
  const [cadence, setCadence] = useState(isYearly(commitment) ? 'yearly' : commitment.cadence)
  const [nextDate, setNextDate] = useState(commitment.next_date)
  const [matchMerchant, setMatchMerchant] = useState(merchantFromKey(commitment.match_key))
  const [saving, setSaving] = useState(false)

  const isExpense = commitment.direction === 'expense'

  const save = async () => {
    setSaving(true)
    try {
      await analyticsAPI.updateCommitment(commitment.id, {
        label,
        amount: Number(amount),
        // Yearly is stored as every-12-months.
        cadence: cadence === 'yearly' ? 'every_n_months' : cadence,
        interval_months:
          cadence === 'yearly'
            ? 12
            : cadence === 'every_n_months'
            ? (Number(commitment.interval_months) >= 12 ? 3 : commitment.interval_months ?? 3)
            : null,
        next_date: nextDate,
        // Only send when it changed, so we never blank an auto-detected key.
        ...(matchMerchant !== merchantFromKey(commitment.match_key)
          ? { match_merchant: matchMerchant }
          : {}),
      })
      onSaved()
    } catch (e) {
      console.error('Failed to edit commitment', e)
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-4">Edit commitment</h3>
        <div className="space-y-3">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Name" className="input" />
          <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount (£)" className="input" />
          <select value={cadence} onChange={(e) => setCadence(e.target.value)} className="input">
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="every_n_months">Every few months</option>
            <option value="yearly">Yearly</option>
            <option value="custom_days">Custom</option>
          </select>
          <div>
            <label className="label">Next date</label>
            <input type="date" value={nextDate} onChange={(e) => setNextDate(e.target.value)} className="input" />
          </div>
          {isExpense && (
            <div>
              <label className="label">Matches transactions from</label>
              <input
                value={matchMerchant}
                onChange={(e) => setMatchMerchant(e.target.value)}
                placeholder="e.g. the name on your rent payment"
                className="input"
              />
              <p className="text-xs text-slate-500 mt-1">
                The merchant or description as it appears on the transaction. This is how
                “Exclude commitments” knows to hide it from spending.
              </p>
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
