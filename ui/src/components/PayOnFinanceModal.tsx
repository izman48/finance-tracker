import { useState } from 'react'
import { analyticsAPI } from '../services/api'
import { Transaction } from '../types'
import { gbp } from '../lib/format'

export default function PayOnFinanceModal({
  transaction,
  onClose,
  onDone,
}: {
  transaction: Transaction
  onClose: () => void
  onDone: (label: string) => void
}) {
  const label = transaction.merchant_name || transaction.description || 'this purchase'
  const [months, setMonths] = useState(12)
  // Default the per-month amount to an even split of the purchase, rounded to pennies.
  const [monthly, setMonthly] = useState(() => (transaction.amount / 12).toFixed(2))
  // First payment defaults to ~a month out.
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setMonth(d.getMonth() + 1)
    return d.toISOString().slice(0, 10)
  })
  const [saving, setSaving] = useState(false)

  const setMonthsAndSplit = (m: number) => {
    setMonths(m)
    setMonthly((transaction.amount / Math.max(m, 1)).toFixed(2))
  }

  const total = (Number(monthly) || 0) * months

  const save = async () => {
    if (!months || !monthly || Number(monthly) <= 0 || !startDate) return
    setSaving(true)
    try {
      await analyticsAPI.payOnFinance({
        transaction_id: transaction.id,
        months,
        monthly_amount: Number(monthly),
        start_date: startDate,
      })
      onDone(label)
    } catch (e) {
      console.error('Failed to move to a payment plan', e)
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel !max-w-sm" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">Pay on finance</h3>
        <p className="text-sm text-slate-400 mb-4">
          Split <span className="font-medium text-slate-200">{label}</span> ({gbp(transaction.amount)})
          into a payment plan. It leaves your Spending totals and the installments show in your forecast.
        </p>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className="label">Number of months</label>
            <input
              type="number" min={1} max={120} value={months}
              onChange={(e) => setMonthsAndSplit(Number(e.target.value))}
              className="input"
            />
          </div>
          <div>
            <label className="label">Amount per month (£)</label>
            <input
              type="number" min={0} step="0.01" value={monthly}
              onChange={(e) => setMonthly(e.target.value)}
              className="input"
            />
          </div>
          <div className="col-span-2">
            <label className="label">First payment</label>
            <input
              type="date" value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="input"
            />
          </div>
        </div>
        <p className="text-xs text-slate-500 mb-4">
          {gbp(Number(monthly) || 0)} × {months} = {gbp(total)} total
          {Math.abs(total - transaction.amount) > 0.5 && (
            <span className="text-slate-400"> · {gbp(total - transaction.amount)} vs the purchase</span>
          )}
        </p>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-ghost">Cancel</button>
          <button onClick={save} disabled={saving} className="btn-primary">
            {saving ? 'Saving…' : 'Move to plan'}
          </button>
        </div>
      </div>
    </div>
  )
}
