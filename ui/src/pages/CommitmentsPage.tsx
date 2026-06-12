import { useEffect, useState } from 'react'
import { analyticsAPI } from '../services/api'
import useReveal from '../components/ui/useReveal'

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

// Yearly is stored as every-12-months; it gets its own section and labels.
const isYearly = (c: Commitment) =>
  c.cadence === 'every_n_months' && Number(c.interval_months) >= 12

const cadenceLabel = (c: Commitment) =>
  isYearly(c) ? 'Yearly' : CADENCE_LABEL[c.cadence] ?? c.cadence

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

  const revealRef = useReveal(!loading)

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
  const yearly = confirmed.filter(isYearly)
  const regular = confirmed.filter((c) => !isYearly(c))
  const confirmedIncome = regular.filter((c) => c.direction === 'income')
  const confirmedExpense = regular.filter((c) => c.direction === 'expense')

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="text-center py-12 text-slate-500">Analyzing your recurring money…</div>
      </div>
    )
  }

  return (
    <div ref={revealRef} className="max-w-5xl mx-auto px-4 py-6 sm:py-10">
      <div className="flex items-center justify-between mb-2">
        <h1 className="font-display font-bold text-2xl sm:text-3xl text-slate-50">Plan</h1>
        <button onClick={() => setShowAdd(true)} className="btn-primary">
          Add manually
        </button>
      </div>
      <p className="text-slate-400 mb-8">
        These regular incomes and bills drive your safe-to-spend and forecast. Confirm the ones that are
        right so the numbers can be trusted.
      </p>

      {/* Suggestions to review */}
      {suggested.length > 0 && (
        <div className="mb-8" data-reveal>
          <h2 className="font-display font-semibold text-lg text-slate-100 mb-3">
            Detected — please review <span className="text-sm font-normal text-slate-500">({suggested.length})</span>
          </h2>
          <div className="card divide-y divide-white/[0.06]">
            {suggested.map((c) => (
              <div key={c.id} className="p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div>
                  <div className="font-medium text-slate-200">
                    {c.label}{' '}
                    <span className={c.direction === 'income' ? 'chip-pos' : 'chip'}>
                      {c.direction}
                    </span>
                  </div>
                  <div className="text-sm text-slate-500">
                    {cadenceLabel(c)} · next {formatDate(c.next_date)}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-slate-100 tnum">{formatCurrency(c.amount)}</span>
                  <button onClick={() => setEditing(c)} className="text-sm text-slate-500 hover:text-accent transition-colors">
                    Edit
                  </button>
                  <button onClick={() => setStatus(c.id, 'confirmed')} className="btn-primary !py-1.5 !px-3">
                    Confirm
                  </button>
                  <button onClick={() => setStatus(c.id, 'dismissed')} className="btn-ghost !py-1.5 !px-3">
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Confirmed */}
      <div className="grid md:grid-cols-2 gap-4 sm:gap-6" data-reveal>
        <ConfirmedList title="Regular income" items={confirmedIncome} onRemove={(id) => setStatus(id, 'dismissed')} onEdit={setEditing} positive />
        <ConfirmedList title="Regular expenses" items={confirmedExpense} onRemove={(id) => setStatus(id, 'dismissed')} onEdit={setEditing} />
      </div>

      {/* Yearly commitments — billed once a year, so they get their own totals
          rather than muddying the monthly numbers. */}
      {yearly.length > 0 && (
        <YearlyList
          items={yearly}
          onRemove={(id) => setStatus(id, 'dismissed')}
          onEdit={setEditing}
        />
      )}

      {/* One-time items */}
      {planned.length > 0 && (
        <div className="mt-6 card" data-reveal>
          <div className="px-4 py-3 border-b border-white/[0.06] font-display font-semibold text-slate-100">One-time</div>
          <div className="divide-y divide-white/[0.06]">
            {planned.map((p) => {
              const isIncome = p.direction === 'income'
              return (
                <div key={p.id} className="p-4 flex items-center justify-between">
                  <div>
                    <div className="font-medium text-slate-200">
                      {p.name} <span className={isIncome ? 'chip-pos' : 'chip'}>{p.direction}</span>
                    </div>
                    <div className="text-sm text-slate-500">{formatDate(p.start_date)}</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`font-semibold tnum ${isIncome ? 'text-pos' : 'text-slate-100'}`}>
                      {isIncome ? '+' : ''}{formatCurrency(p.amount ?? 0)}
                    </span>
                    <button onClick={() => removePlanned(p.id)} className="text-sm text-slate-500 hover:text-neg transition-colors">
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
        <div className="card p-8 text-center text-slate-500 text-sm mt-6">
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
  // Cadences differ, so total as a monthly equivalent. (amount arrives as a
  // string from the API — coerce before arithmetic.)
  const monthlyEquivalent = (c: Commitment) => {
    const amount = Number(c.amount) || 0
    if (c.cadence === 'weekly') return amount * (52 / 12)
    if (c.cadence === 'every_n_months') return amount / (c.interval_months || 1)
    if (c.cadence === 'custom_days') return amount * (30.44 / (c.interval_days || 30))
    return amount
  }
  const total = items.reduce((sum, c) => sum + monthlyEquivalent(c), 0)
  const sorted = [...items].sort((a, b) => monthlyEquivalent(b) - monthlyEquivalent(a))

  return (
    <div className="card">
      <div className="px-4 py-3 border-b border-white/[0.06] flex items-center justify-between">
        <span className="font-display font-semibold text-slate-100">{title}</span>
        {items.length > 0 && (
          <span className={`text-sm font-semibold tnum ${positive ? 'text-pos' : 'text-slate-100'}`}>
            {positive ? '+' : ''}{formatCurrency(total)}/mo
          </span>
        )}
      </div>
      {items.length === 0 ? (
        <div className="p-4 text-sm text-slate-600">None confirmed yet.</div>
      ) : (
        <div className="divide-y divide-white/[0.06]">
          {sorted.map((c) => (
            <div key={c.id} className="p-4 flex items-center justify-between">
              <div>
                <div className="font-medium text-slate-200">{c.label}</div>
                <div className="text-sm text-slate-500">
                  {cadenceLabel(c)} · next {formatDate(c.next_date)}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`font-semibold tnum ${positive ? 'text-pos' : 'text-slate-100'}`}>
                  {positive ? '+' : ''}{formatCurrency(c.amount)}
                </span>
                <button onClick={() => onEdit(c)} className="text-sm text-slate-500 hover:text-accent transition-colors">
                  Edit
                </button>
                <button onClick={() => onRemove(c.id)} className="text-sm text-slate-500 hover:text-neg transition-colors">
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

function YearlyList({
  items,
  onRemove,
  onEdit,
}: {
  items: Commitment[]
  onRemove: (id: string) => void
  onEdit: (c: Commitment) => void
}) {
  const expenseTotal = items
    .filter((c) => c.direction === 'expense')
    .reduce((sum, c) => sum + (Number(c.amount) || 0), 0)
  const incomeTotal = items
    .filter((c) => c.direction === 'income')
    .reduce((sum, c) => sum + (Number(c.amount) || 0), 0)
  const sorted = [...items].sort(
    (a, b) => new Date(a.next_date).getTime() - new Date(b.next_date).getTime(),
  )

  return (
    <div className="mt-6 card" data-reveal>
      <div className="px-4 py-3 border-b border-white/[0.06] flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-display font-semibold text-slate-100">Yearly</span>
          <span className="ml-2 text-xs text-slate-500">billed once a year — sorted by next due</span>
        </div>
        <div className="text-sm tnum text-right">
          {expenseTotal > 0 && (
            <span className="font-semibold text-slate-100">
              {formatCurrency(expenseTotal)}/yr
              <span className="text-slate-500 font-normal"> ≈ {formatCurrency(expenseTotal / 12)}/mo</span>
            </span>
          )}
          {incomeTotal > 0 && (
            <span className={`font-semibold text-pos ${expenseTotal > 0 ? 'ml-4' : ''}`}>
              +{formatCurrency(incomeTotal)}/yr
            </span>
          )}
        </div>
      </div>
      <div className="divide-y divide-white/[0.06]">
        {sorted.map((c) => {
          const income = c.direction === 'income'
          return (
            <div key={c.id} className="p-4 flex items-center justify-between">
              <div>
                <div className="font-medium text-slate-200">
                  {c.label} {income && <span className="chip-pos">income</span>}
                </div>
                <div className="text-sm text-slate-500">due {formatDate(c.next_date)}</div>
              </div>
              <div className="flex items-center gap-3">
                <span className={`font-semibold tnum ${income ? 'text-pos' : 'text-slate-100'}`}>
                  {income ? '+' : ''}{formatCurrency(c.amount)}
                </span>
                <button onClick={() => onEdit(c)} className="text-sm text-slate-500 hover:text-accent transition-colors">
                  Edit
                </button>
                <button onClick={() => onRemove(c.id)} className="text-sm text-slate-500 hover:text-neg transition-colors">
                  Remove
                </button>
              </div>
            </div>
          )
        })}
      </div>
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
  const [cadence, setCadence] = useState(isYearly(commitment) ? 'yearly' : commitment.cadence)
  const [nextDate, setNextDate] = useState(commitment.next_date)
  const [saving, setSaving] = useState(false)

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
          // Yearly is stored as every-12-months.
          cadence: frequency === 'yearly' ? 'every_n_months' : frequency,
          interval_months: frequency === 'yearly' ? 12 : undefined,
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
