import { useEffect, useState } from 'react'
import { analyticsAPI } from '../services/api'

interface PlannedItem {
  id: string
  name: string
  direction: string
  kind: string
  start_date: string
  amount: number | null
  total_amount: number | null
  installments: number | null
}

const gbp = (n: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n)
const shortDate = (d: string) => new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

// Mirrors backend analytics_service.installment_amount (even split + simple interest + fee).
function perInstallment(total: number, n: number, apr: number, fee: number) {
  if (!n) return 0
  let base = total
  if (fee) base += fee
  if (apr) base += total * (apr / 100) * (n / 12)
  return Math.round((base / n) * 100) / 100
}

function addMonths(iso: string, months: number) {
  const d = new Date(iso)
  d.setMonth(d.getMonth() + months)
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

export default function PlannedItems({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<PlannedItem[]>([])
  const [showAdd, setShowAdd] = useState(false)

  const load = async () => {
    try {
      const res = await analyticsAPI.getPlannedItems()
      setItems(res.data)
    } catch (e) {
      console.error('Failed to load planned items', e)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const remove = async (id: string) => {
    await analyticsAPI.deletePlannedItem(id)
    await load()
    onChanged()
  }

  const describe = (it: PlannedItem) => {
    if (it.kind === 'installment_plan')
      return `${gbp(it.total_amount ?? 0)} over ${it.installments} payments · from ${shortDate(it.start_date)}`
    if (it.kind === 'recurring') return `${gbp(it.amount ?? 0)} recurring · from ${shortDate(it.start_date)}`
    return `${gbp(it.amount ?? 0)} · ${shortDate(it.start_date)}`
  }

  return (
    <div className="p-6 bg-white rounded-xl shadow-sm border border-gray-200">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">Planned</h2>
        <button onClick={() => setShowAdd(true)} className="text-sm text-blue-600 hover:text-blue-800">
          + Add planned item
        </button>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-gray-400">
          Nothing planned. Add an upcoming cost, expected income, or split a big purchase to see how it hits your forecast.
        </p>
      ) : (
        <div className="divide-y">
          {items.map((it) => (
            <div key={it.id} className="py-3 flex items-center justify-between">
              <div>
                <div className="font-medium">
                  {it.name}
                  {it.direction === 'income' && (
                    <span className="ml-2 text-xs px-2 py-0.5 rounded bg-green-100 text-green-700">income</span>
                  )}
                </div>
                <div className={`text-sm ${it.direction === 'income' ? 'text-green-600' : 'text-gray-500'}`}>
                  {it.direction === 'income' ? '+' : ''}{describe(it)}
                </div>
              </div>
              <button onClick={() => remove(it.id)} className="text-sm text-gray-400 hover:text-red-600">
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <AddPlannedModal
          onClose={() => setShowAdd(false)}
          onAdded={async () => {
            setShowAdd(false)
            await load()
            onChanged()
          }}
        />
      )}
    </div>
  )
}

function AddPlannedModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [direction, setDirection] = useState('expense')
  const [kind, setKind] = useState('one_off')
  const [name, setName] = useState('')
  const [startDate, setStartDate] = useState('')
  const [amount, setAmount] = useState('')
  const [cadence, setCadence] = useState('monthly')
  const [total, setTotal] = useState('')
  const [installments, setInstallments] = useState('3')
  const [withInterest, setWithInterest] = useState(false)
  const [apr, setApr] = useState('')
  const [fee, setFee] = useState('')
  const [saving, setSaving] = useState(false)

  const n = Number(installments) || 0
  const per = perInstallment(Number(total) || 0, n, withInterest ? Number(apr) || 0 : 0, withInterest ? Number(fee) || 0 : 0)

  const save = async () => {
    if (!name || !startDate) return
    setSaving(true)
    const base: Record<string, unknown> = { name, direction, kind, start_date: startDate }
    if (kind === 'installment_plan') {
      Object.assign(base, {
        total_amount: Number(total),
        installments: n,
        cadence,
        apr: withInterest && apr ? Number(apr) : null,
        fee_amount: withInterest && fee ? Number(fee) : null,
      })
    } else if (kind === 'recurring') {
      Object.assign(base, { amount: Number(amount), cadence })
    } else {
      Object.assign(base, { amount: Number(amount) })
    }
    try {
      await analyticsAPI.addPlannedItem(base)
      onAdded()
    } catch (e) {
      console.error('Failed to add planned item', e)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-4">
          Add planned {direction === 'income' ? 'income' : 'expense'}
        </h3>

        <div className="grid grid-cols-2 gap-2 mb-3">
          {[
            { d: 'expense', l: 'Expense' },
            { d: 'income', l: 'Income' },
          ].map((o) => (
            <button
              key={o.d}
              onClick={() => {
                setDirection(o.d)
                if (o.d === 'income' && kind === 'installment_plan') setKind('one_off')
              }}
              className={`py-2 text-sm rounded-lg border ${
                direction === o.d
                  ? o.d === 'income'
                    ? 'border-green-600 bg-green-50'
                    : 'border-blue-600 bg-blue-50'
                  : 'border-gray-300'
              }`}
            >
              {o.l}
            </button>
          ))}
        </div>

        <div className={`grid ${direction === 'income' ? 'grid-cols-2' : 'grid-cols-3'} gap-2 mb-4`}>
          {[
            { k: 'one_off', l: 'One-off' },
            { k: 'recurring', l: 'Recurring' },
            // Splitting a total into N payments only makes sense for spending
            ...(direction === 'expense' ? [{ k: 'installment_plan', l: 'Payment plan' }] : []),
          ].map((o) => (
            <button
              key={o.k}
              onClick={() => setKind(o.k)}
              className={`py-2 text-sm rounded-lg border ${kind === o.k ? 'border-blue-600 bg-blue-50' : 'border-gray-300'}`}
            >
              {o.l}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={direction === 'income' ? 'Name (e.g. Tax refund)' : 'Name (e.g. New laptop)'}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          />

          {kind === 'installment_plan' ? (
            <>
              <input type="number" value={total} onChange={(e) => setTotal(e.target.value)} placeholder="Total amount (£)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
              <div className="grid grid-cols-2 gap-3">
                <input type="number" min={1} value={installments} onChange={(e) => setInstallments(e.target.value)} placeholder="Payments" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
                <select value={cadence} onChange={(e) => setCadence(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg">
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>
              <label className="flex items-center text-sm text-gray-700">
                <input type="checkbox" checked={withInterest} onChange={(e) => setWithInterest(e.target.checked)} className="mr-2" />
                Add interest / fees
              </label>
              {withInterest && (
                <div className="grid grid-cols-2 gap-3">
                  <input type="number" value={apr} onChange={(e) => setApr(e.target.value)} placeholder="APR %" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
                  <input type="number" value={fee} onChange={(e) => setFee(e.target.value)} placeholder="Fee (£)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
                </div>
              )}
              {n > 0 && Number(total) > 0 && (
                <div className="bg-gray-50 rounded-lg p-3 text-sm">
                  <div className="font-medium">{gbp(per)} × {n} payments</div>
                  <div className="text-gray-500 mt-1">
                    {Array.from({ length: Math.min(n, 4) }).map((_, i) => (
                      <span key={i}>{addMonths(startDate || new Date().toISOString(), i)}{i < Math.min(n, 4) - 1 ? ' · ' : ''}</span>
                    ))}
                    {n > 4 && ' …'}
                  </div>
                  <div className="text-gray-400 mt-1">Total payable {gbp(per * n)}</div>
                </div>
              )}
            </>
          ) : (
            <>
              <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount (£)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
              {kind === 'recurring' && (
                <select value={cadence} onChange={(e) => setCadence(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg">
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              )}
            </>
          )}

          <div>
            <label className="block text-sm text-gray-600 mb-1">{kind === 'one_off' ? 'Date' : 'Start date'}</label>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button onClick={save} disabled={saving} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Add'}
          </button>
        </div>
      </div>
    </div>
  )
}
