import { useEffect, useState } from 'react'
import { analyticsAPI } from '../services/api'

interface Goal {
  id: string
  name: string
  target_amount: number
  target_date: string | null
  linked_account_id: string | null
  current: number
  remaining: number
  progress_pct: number
  complete: boolean
  overdue: boolean
  months_left: number | null
  monthly_needed: number | null
  on_track: boolean | null
}

interface SavingsAccount {
  id: string
  display_name: string
  role: string
}

interface Holding {
  id: string
  name: string
  provider: string | null
  current_value: number
  external_url: string | null
  updated_at: string
}

const gbp = (n: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(n)
const longDate = (d: string) => new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })

export default function SavingsPage() {
  const [savable, setSavable] = useState(0)
  const [goals, setGoals] = useState<Goal[]>([])
  const [savingsAccounts, setSavingsAccounts] = useState<SavingsAccount[]>([])
  const [holdings, setHoldings] = useState<Holding[]>([])
  const [holdingsTotal, setHoldingsTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Goal | 'new' | null>(null)
  const [editingHolding, setEditingHolding] = useState<Holding | 'new' | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [g, s, h] = await Promise.all([
        analyticsAPI.getGoals(),
        analyticsAPI.getSummary(),
        analyticsAPI.getHoldings(),
      ])
      setSavable(Number(g.data.savable))
      setGoals(
        g.data.goals.map((x: any) => ({
          ...x,
          target_amount: Number(x.target_amount),
          current: Number(x.current),
          remaining: Number(x.remaining),
          monthly_needed: x.monthly_needed == null ? null : Number(x.monthly_needed),
        })),
      )
      setSavingsAccounts((s.data.accounts || []).filter((a: SavingsAccount) => a.role === 'savings'))
      setHoldings(h.data.holdings.map((x: any) => ({ ...x, current_value: Number(x.current_value) })))
      setHoldingsTotal(Number(h.data.total))
    } catch (e) {
      console.error('Failed to load savings', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const remove = async (id: string) => {
    await analyticsAPI.deleteGoal(id)
    await load()
  }

  const removeHolding = async (id: string) => {
    await analyticsAPI.deleteHolding(id)
    await load()
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-3xl font-bold">Savings goals</h1>
        <button onClick={() => setEditing('new')} className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
          Add goal
        </button>
      </div>

      <div className="mb-6 grid sm:grid-cols-2 gap-4">
        <div className="p-5 bg-white rounded-xl shadow-sm border border-gray-200">
          <div className="text-sm text-gray-500">Savable this period</div>
          <div className="text-3xl font-bold text-green-600">{gbp(savable)}</div>
          <div className="text-xs text-gray-400 mt-1">projected surplus you could put toward goals without missing commitments</div>
        </div>
        <div className="p-5 bg-white rounded-xl shadow-sm border border-gray-200">
          <div className="text-sm text-gray-500">Invested</div>
          <div className="text-3xl font-bold">{gbp(holdingsTotal)}</div>
          <div className="text-xs text-gray-400 mt-1">total across your investment / ISA holdings</div>
        </div>
      </div>

      {/* Investments / ISA */}
      <div className="mb-8 bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="px-5 py-3 border-b flex items-center justify-between">
          <h2 className="font-semibold">Investments &amp; ISA</h2>
          <button onClick={() => setEditingHolding('new')} className="text-sm text-blue-600 hover:text-blue-800">
            + Add holding
          </button>
        </div>
        {holdings.length === 0 ? (
          <p className="p-5 text-sm text-gray-400">
            Add your ISA or investment value (e.g. InvestEngine). Values are entered manually —
            providers like InvestEngine don't offer a public balance API yet.
          </p>
        ) : (
          <div className="divide-y">
            {holdings.map((h) => (
              <div key={h.id} className="p-5 flex items-center justify-between">
                <div>
                  <div className="font-medium">
                    {h.name}
                    {h.provider && <span className="text-gray-400 text-sm"> · {h.provider}</span>}
                  </div>
                  <div className="text-sm text-gray-500">
                    as of {longDate(h.updated_at)}
                    {h.external_url && (
                      <>
                        {' · '}
                        <a href={h.external_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:text-blue-800">
                          open ↗
                        </a>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-semibold">{gbp(h.current_value)}</span>
                  <button onClick={() => setEditingHolding(h)} className="text-sm text-gray-400 hover:text-blue-600">Edit</button>
                  <button onClick={() => removeHolding(h.id)} className="text-sm text-gray-400 hover:text-red-600">Remove</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <h2 className="text-xl font-semibold mb-3">Goals</h2>
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading…</div>
      ) : goals.length === 0 ? (
        <div className="p-8 bg-white rounded-xl shadow-sm text-center text-gray-500">
          No goals yet. Add one to track progress toward a target.
        </div>
      ) : (
        <div className="space-y-4">
          {goals.map((g) => (
            <div key={g.id} className="p-5 bg-white rounded-xl shadow-sm border border-gray-200">
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h3 className="font-semibold text-lg">
                    {g.name}{' '}
                    {g.complete && <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700">Reached 🎉</span>}
                    {g.overdue && <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700">Overdue</span>}
                  </h3>
                  <p className="text-sm text-gray-500">
                    {gbp(g.current)} of {gbp(g.target_amount)}
                    {g.target_date && ` · by ${longDate(g.target_date)}`}
                    {g.linked_account_id && ' · auto from linked account'}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setEditing(g)} className="text-sm text-gray-400 hover:text-blue-600">Edit</button>
                  <button onClick={() => remove(g.id)} className="text-sm text-gray-400 hover:text-red-600">Remove</button>
                </div>
              </div>

              <div className="bg-gray-100 rounded-full h-3 mb-2">
                <div
                  className={`h-3 rounded-full ${g.complete ? 'bg-green-500' : 'bg-blue-600'}`}
                  style={{ width: `${Math.min(100, g.progress_pct)}%` }}
                />
              </div>

              <div className="flex justify-between text-sm">
                <span className="text-gray-500">{g.progress_pct}% · {gbp(g.remaining)} to go</span>
                {g.monthly_needed != null && !g.complete && (
                  <span className={g.on_track ? 'text-green-600' : 'text-red-600'}>
                    {gbp(g.monthly_needed)}/mo needed{g.on_track ? ' · on track' : ' · over your savable'}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <GoalModal
          goal={editing === 'new' ? null : editing}
          savingsAccounts={savingsAccounts}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await load()
          }}
        />
      )}

      {editingHolding && (
        <HoldingModal
          holding={editingHolding === 'new' ? null : editingHolding}
          onClose={() => setEditingHolding(null)}
          onSaved={async () => {
            setEditingHolding(null)
            await load()
          }}
        />
      )}
    </div>
  )
}

function HoldingModal({
  holding,
  onClose,
  onSaved,
}: {
  holding: Holding | null
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(holding?.name ?? '')
  const [provider, setProvider] = useState(holding?.provider ?? '')
  const [value, setValue] = useState(holding ? String(holding.current_value) : '')
  const [url, setUrl] = useState(holding?.external_url ?? '')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!name || value === '') return
    setSaving(true)
    const payload = {
      name,
      provider: provider || null,
      current_value: Number(value),
      external_url: url || null,
    }
    try {
      if (holding) await analyticsAPI.updateHolding(holding.id, payload)
      else await analyticsAPI.addHolding(payload)
      onSaved()
    } catch (e) {
      console.error('Failed to save holding', e)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">{holding ? 'Update holding' : 'Add investment / ISA'}</h3>
        <p className="text-sm text-gray-500 mb-4">Enter the current value yourself — update it whenever you check the provider.</p>
        <div className="space-y-3">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (e.g. InvestEngine ISA)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          <input value={provider} onChange={(e) => setProvider(e.target.value)} placeholder="Provider (optional, e.g. InvestEngine)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          <input type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Current value (£)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Portfolio link (optional)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
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

function GoalModal({
  goal,
  savingsAccounts,
  onClose,
  onSaved,
}: {
  goal: Goal | null
  savingsAccounts: SavingsAccount[]
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(goal?.name ?? '')
  const [target, setTarget] = useState(goal ? String(goal.target_amount) : '')
  const [targetDate, setTargetDate] = useState(goal?.target_date ?? '')
  const [linked, setLinked] = useState(goal?.linked_account_id ?? '')
  const [current, setCurrent] = useState(goal && !goal.linked_account_id ? String(goal.current) : '')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!name || !target) return
    setSaving(true)
    const payload: Record<string, unknown> = {
      name,
      target_amount: Number(target),
      target_date: targetDate || null,
      linked_account_id: linked || null,
      current_amount: linked ? 0 : Number(current || 0),
    }
    try {
      if (goal) await analyticsAPI.updateGoal(goal.id, payload)
      else await analyticsAPI.addGoal(payload)
      onSaved()
    } catch (e) {
      console.error('Failed to save goal', e)
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-4">{goal ? 'Edit goal' : 'New savings goal'}</h3>
        <div className="space-y-3">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (e.g. Emergency fund)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          <input type="number" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="Target amount (£)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          <div>
            <label className="block text-sm text-gray-600 mb-1">Target date (optional)</label>
            <input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Track progress from</label>
            <select value={linked} onChange={(e) => setLinked(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg">
              <option value="">Enter manually</option>
              {savingsAccounts.map((a) => (
                <option key={a.id} value={a.id}>{a.display_name} (balance)</option>
              ))}
            </select>
          </div>
          {!linked && (
            <input type="number" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Saved so far (£)" className="w-full px-3 py-2 border border-gray-300 rounded-lg" />
          )}
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
