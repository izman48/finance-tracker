import { useState } from 'react'
import { analyticsAPI } from '../services/api'

export default function AddCommitmentModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [direction, setDirection] = useState('expense')
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState('')
  const [frequency, setFrequency] = useState('monthly') // one_time | weekly | monthly | every_n_months
  const [theDate, setTheDate] = useState('')
  const [matchMerchant, setMatchMerchant] = useState('')
  const [saving, setSaving] = useState(false)

  const isOneTime = frequency === 'one_time'
  const isExpense = direction === 'expense'

  const save = async () => {
    if (!label || !amount || !theDate) return
    setSaving(true)
    try {
      if (isOneTime) {
        await analyticsAPI.addPlannedItem({
          name: label,
          direction,
          kind: 'one_off',
          start_date: theDate,
          amount: Number(amount),
        })
      } else {
        await analyticsAPI.addCommitment({
          direction,
          label,
          amount: Number(amount),
          // Yearly is stored as every-12-months.
          cadence: frequency === 'yearly' ? 'every_n_months' : frequency,
          interval_months: frequency === 'yearly' ? 12 : undefined,
          next_date: theDate,
          match_merchant: isExpense && matchMerchant ? matchMerchant : undefined,
        })
      }
      onAdded()
    } catch (e) {
      console.error('Failed to add item', e)
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-4">Add income or expense</h3>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => setDirection('expense')}
              className={`py-2 rounded-xl border text-sm transition-colors ${
                direction === 'expense' ? 'border-accent/60 bg-accent/10 text-accent' : 'border-white/10 text-slate-300 hover:bg-white/[0.04]'
              }`}
            >
              Expense
            </button>
            <button
              onClick={() => setDirection('income')}
              className={`py-2 rounded-xl border text-sm transition-colors ${
                direction === 'income' ? 'border-pos/60 bg-pos/10 text-pos' : 'border-white/10 text-slate-300 hover:bg-white/[0.04]'
              }`}
            >
              Income
            </button>
          </div>
          <input
            value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Name (e.g. Rent)"
            className="input"
          />
          <input
            type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount (£)"
            className="input"
          />
          <select value={frequency} onChange={(e) => setFrequency(e.target.value)} className="input">
            <option value="one_time">One-time</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="every_n_months">Every few months</option>
            <option value="yearly">Yearly</option>
          </select>
          <div>
            <label className="label">{isOneTime ? 'Date' : 'Next date'}</label>
            <input
              type="date" value={theDate} onChange={(e) => setTheDate(e.target.value)}
              className="input"
            />
          </div>
          {isExpense && !isOneTime && (
            <div>
              <label className="label">Matches transactions from <span className="text-slate-500 font-normal">(optional)</span></label>
              <input
                value={matchMerchant} onChange={(e) => setMatchMerchant(e.target.value)}
                placeholder="e.g. the name on your rent payment"
                className="input"
              />
              <p className="text-xs text-slate-500 mt-1">
                Enter the merchant/description as it shows on the transaction so “Exclude
                commitments” can hide it. Tip: you can also tap a transaction in Activity
                and “Mark as recurring” to capture it exactly.
              </p>
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? 'Saving…' : 'Add'}
          </button>
        </div>
      </div>
    </div>
  )
}
