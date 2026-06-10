import { useEffect, useState } from 'react'
import { analyticsAPI } from '../services/api'

interface Commitment {
  id: string
  direction: 'income' | 'expense'
  label: string
  amount: number
  cadence: string
  interval_days: number | null
  interval_months: number | null
  next_date: string
  source: 'detected' | 'manual'
  status: 'suggested' | 'confirmed' | 'dismissed'
  account_id: string | null
}

interface PlannedOneOff {
  id: string
  name: string
  direction: string
  kind: string
  start_date: string
  amount: number | null
}

const CADENCE_LABEL: Record<string, string> = {
  weekly: 'Weekly',
  monthly: 'Monthly',
  every_n_months: 'Every few months',
  custom_days: 'Custom',
}

function formatCurrency(amount: number) {
  return new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(amount)
}

function formatDate(date: string) {
  return new Date(date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function CommitmentsPage() {
  const [commitments, setCommitments] = useState<Commitment[]>([])
  const [planned, setPlanned] = useState<PlannedOneOff[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState<Commitment | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [c, p] = await Promise.all([
        analyticsAPI.getCommitments(),
        analyticsAPI.getPlannedItems(),
      ])
      setCommitments(c.data)
      setPlanned(p.data.filter((x: PlannedOneOff) => x.kind === 'one_off'))
    } catch (error) {
      console.error('Failed to load commitments:', error)
    } finally {
      setLoading(false)
    }
  }

  const removePlanned = async (id: string) => {
    await analyticsAPI.deletePlannedItem(id)
    await load()
  }

  useEffect(() => {
    load()
  }, [])

  const setStatus = async (id: string, status: string) => {
    await analyticsAPI.updateCommitment(id, { status })
    await load()
  }

  const suggested = commitments.filter((c) => c.status === 'suggested')
  const confirmed = commitments.filter((c) => c.status === 'confirmed')
  const confirmedIncome = confirmed.filter((c) => c.direction === 'income')
  const confirmedExpense = confirmed.filter((c) => c.direction === 'expense')

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="text-center py-12 text-gray-600">Analyzing your recurring money…</div>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl sm:text-3xl font-bold">Commitments</h1>
        <button
          onClick={() => setShowAdd(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
        >
          Add manually
        </button>
      </div>
      <p className="text-gray-600 mb-8">
        These regular incomes and bills drive your safe-to-spend and forecast. Confirm the ones that are
        right so the numbers can be trusted.
      </p>

      {/* Suggestions to review */}
      {suggested.length > 0 && (
        <div className="mb-8">
          <h2 className="text-xl font-semibold mb-3">
            Detected — please review <span className="text-sm font-normal text-gray-500">({suggested.length})</span>
          </h2>
          <div className="bg-white rounded-lg shadow-sm divide-y">
            {suggested.map((c) => (
              <div key={c.id} className="p-4 flex items-center justify-between">
                <div>
                  <div className="font-medium">
                    {c.label}{' '}
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      c.direction === 'income' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                    }`}>
                      {c.direction}
                    </span>
                  </div>
                  <div className="text-sm text-gray-500">
                    {CADENCE_LABEL[c.cadence] ?? c.cadence} · next {formatDate(c.next_date)}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-semibold">{formatCurrency(c.amount)}</span>
                  <button onClick={() => setEditing(c)} className="text-sm text-gray-500 hover:text-blue-600">
                    Edit
                  </button>
                  <button
                    onClick={() => setStatus(c.id, 'confirmed')}
                    className="px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => setStatus(c.id, 'dismissed')}
                    className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded-lg hover:bg-gray-200"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Confirmed */}
      <div className="grid md:grid-cols-2 gap-6">
        <ConfirmedList title="Regular income" items={confirmedIncome} onRemove={(id) => setStatus(id, 'dismissed')} onEdit={setEditing} positive />
        <ConfirmedList title="Regular expenses" items={confirmedExpense} onRemove={(id) => setStatus(id, 'dismissed')} onEdit={setEditing} />
      </div>

      {/* One-time items */}
      {planned.length > 0 && (
        <div className="mt-6 bg-white rounded-lg shadow-sm">
          <div className="px-4 py-3 border-b font-semibold">One-time</div>
          <div className="divide-y">
            {planned.map((p) => {
              const isIncome = p.direction === 'income'
              return (
                <div key={p.id} className="p-4 flex items-center justify-between">
                  <div>
                    <div className="font-medium">
                      {p.name}{' '}
                      <span className={`text-xs px-2 py-0.5 rounded ${isIncome ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
                        {p.direction}
                      </span>
                    </div>
                    <div className="text-sm text-gray-500">{formatDate(p.start_date)}</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`font-semibold ${isIncome ? 'text-green-600' : 'text-gray-900'}`}>
                      {isIncome ? '+' : ''}{formatCurrency(p.amount ?? 0)}
                    </span>
                    <button onClick={() => removePlanned(p.id)} className="text-sm text-gray-400 hover:text-red-600">
                      Remove
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {confirmed.length === 0 && suggested.length === 0 && planned.length === 0 && (
        <div className="p-8 bg-white rounded-lg shadow-sm text-center text-gray-500">
          Nothing yet. Sync more transaction history, or add a commitment / one-time item manually.
        </div>
      )}

      {showAdd && (
        <AddCommitmentModal
          onClose={() => setShowAdd(false)}
          onAdded={async () => {
            setShowAdd(false)
            await load()
          }}
        />
      )}

      {editing && (
        <EditCommitmentModal
          commitment={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await load()
          }}
        />
      )}
    </div>
  )
}

function ConfirmedList({
  title,
  items,
  onRemove,
  onEdit,
  positive,
}: {
  title: string
  items: Commitment[]
  onRemove: (id: string) => void
  onEdit: (c: Commitment) => void
  positive?: boolean
}) {
  // Cadences differ, so total as a monthly equivalent.
  const monthlyEquivalent = (c: Commitment) => {
    if (c.cadence === 'weekly') return c.amount * (52 / 12)
    if (c.cadence === 'every_n_months') return c.amount / (c.interval_months || 1)
    if (c.cadence === 'custom_days') return c.amount * (30.44 / (c.interval_days || 30))
    return c.amount
  }
  const total = items.reduce((sum, c) => sum + monthlyEquivalent(c), 0)

  return (
    <div className="bg-white rounded-lg shadow-sm">
      <div className="px-4 py-3 border-b flex items-center justify-between">
        <span className="font-semibold">{title}</span>
        {items.length > 0 && (
          <span className={`text-sm font-semibold ${positive ? 'text-green-600' : 'text-gray-900'}`}>
            {positive ? '+' : ''}{formatCurrency(total)}/mo
          </span>
        )}
      </div>
      {items.length === 0 ? (
        <div className="p-4 text-sm text-gray-400">None confirmed yet.</div>
      ) : (
        <div className="divide-y">
          {items.map((c) => (
            <div key={c.id} className="p-4 flex items-center justify-between">
              <div>
                <div className="font-medium">{c.label}</div>
                <div className="text-sm text-gray-500">
                  {CADENCE_LABEL[c.cadence] ?? c.cadence} · next {formatDate(c.next_date)}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`font-semibold ${positive ? 'text-green-600' : 'text-gray-900'}`}>
                  {positive ? '+' : ''}{formatCurrency(c.amount)}
                </span>
                <button onClick={() => onEdit(c)} className="text-sm text-gray-400 hover:text-blue-600">
                  Edit
                </button>
                <button onClick={() => onRemove(c.id)} className="text-sm text-gray-400 hover:text-red-600">
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function EditCommitmentModal({
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
  const [cadence, setCadence] = useState(commitment.cadence)
  const [nextDate, setNextDate] = useState(commitment.next_date)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      await analyticsAPI.updateCommitment(commitment.id, {
        label,
        amount: Number(amount),
        cadence,
        next_date: nextDate,
      })
      onSaved()
    } catch (e) {
      console.error('Failed to edit commitment', e)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-4">Edit commitment</h3>
        <div className="space-y-3">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Name" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount (£)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          <select value={cadence} onChange={(e) => setCadence(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg">
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="every_n_months">Every few months</option>
            <option value="custom_days">Custom</option>
          </select>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Next date</label>
            <input type="date" value={nextDate} onChange={(e) => setNextDate(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button onClick={save} disabled={saving} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

function AddCommitmentModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [direction, setDirection] = useState('expense')
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState('')
  const [frequency, setFrequency] = useState('monthly') // one_time | weekly | monthly | every_n_months
  const [theDate, setTheDate] = useState('')
  const [saving, setSaving] = useState(false)

  const isOneTime = frequency === 'one_time'

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
          cadence: frequency,
          next_date: theDate,
        })
      }
      onAdded()
    } catch (e) {
      console.error('Failed to add item', e)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-4">Add income or expense</h3>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => setDirection('expense')}
              className={`py-2 rounded-lg border ${direction === 'expense' ? 'border-blue-600 bg-blue-50' : 'border-gray-300'}`}
            >
              Expense
            </button>
            <button
              onClick={() => setDirection('income')}
              className={`py-2 rounded-lg border ${direction === 'income' ? 'border-blue-600 bg-blue-50' : 'border-gray-300'}`}
            >
              Income
            </button>
          </div>
          <input
            value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Name (e.g. Rent)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          />
          <input
            type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount (£)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          />
          <select value={frequency} onChange={(e) => setFrequency(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg">
            <option value="one_time">One-time</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="every_n_months">Every few months</option>
          </select>
          <div>
            <label className="block text-sm text-gray-600 mb-1">{isOneTime ? 'Date' : 'Next date'}</label>
            <input
              type="date" value={theDate} onChange={(e) => setTheDate(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-lg">Cancel</button>
          <button
            onClick={save} disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Add'}
          </button>
        </div>
      </div>
    </div>
  )
}
