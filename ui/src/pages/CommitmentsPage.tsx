import { useEffect, useState } from 'react'
import { analyticsAPI } from '../services/api'
import { Commitment, PlannedItem } from '../types'
import { gbp as formatCurrency, dateLong as formatDate } from '../lib/format'
import { cadenceLabel, isYearly, monthlyEquivalent } from '../lib/cadence'
import AddCommitmentModal from '../components/AddCommitmentModal'
import EditCommitmentModal from '../components/EditCommitmentModal'
import useReveal from '../components/ui/useReveal'

export default function CommitmentsPage() {
  const [commitments, setCommitments] = useState<Commitment[]>([])
  const [planned, setPlanned] = useState<PlannedItem[]>([])
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
      setPlanned(p.data.filter((x: PlannedItem) => x.kind === 'one_off'))
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
