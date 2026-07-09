import { useState } from 'react'
import { CreditCard, Repeat, Wand2, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { analyticsAPI, bankingAPI } from '../services/api'
import { Transaction } from '../types'
import { money, dateDMY } from '../lib/format'
import { useToast } from './ui/Toast'

const CADENCES = [
  { key: 'weekly', label: 'Weekly' },
  { key: 'monthly', label: 'Monthly' },
  { key: 'every_n_months', label: 'Every few months' },
  { key: 'yearly', label: 'Yearly' },
]

const EXCLUDED_COPY: Record<string, string> = {
  internal_transfer:
    'Hidden from spending: this looks like money moving between your own accounts.',
  card_payment:
    'Hidden from spending: this settles a credit card — the purchases themselves are what count.',
}

/** Everything you can do to one transaction, in one place: category, "this
 *  repeats" (→ commitments), rule creation, pay on finance. */
export default function TransactionDetailSheet({
  transaction,
  accountName,
  categories,
  onClose,
  onChanged,
  onCreateRule,
  onPayOnFinance,
}: {
  transaction: Transaction
  accountName: string
  categories: string[]
  onClose: () => void
  onChanged: (patch?: Partial<Transaction>) => void
  onCreateRule: () => void
  onPayOnFinance: () => void
}) {
  const showToast = useToast()
  const navigate = useNavigate()
  const [editingCategory, setEditingCategory] = useState(false)
  const [category, setCategory] = useState(transaction.category ?? '')
  const [addingNew, setAddingNew] = useState(false)
  const [newCategory, setNewCategory] = useState('')
  const [savingCadence, setSavingCadence] = useState<string | null>(null)
  // Local mirror of the counts-as override so the sheet reflects a change
  // immediately (the page refetches behind it).
  const [countsAs, setCountsAs] = useState<string | null>(transaction.counts_as_override ?? null)

  const label = transaction.merchant_name || transaction.description
  const isCredit = transaction.transaction_type === 'credit'

  // What this transaction currently counts as: the user's override, else the
  // automatic detection's verdict.
  const effectiveCountsAs =
    countsAs ??
    (transaction.excluded_reason === 'internal_transfer'
      ? 'transfer'
      : transaction.excluded_reason === 'card_payment'
      ? 'card_payment'
      : 'spending')

  const saveCountsAs = async (value: string | null) => {
    try {
      await bankingAPI.updateTransaction(transaction.id, { counts_as: value })
      setCountsAs(value)
      onChanged()
      showToast(
        value === null
          ? 'Back to automatic detection'
          : `Counted as ${value === 'card_payment' ? 'a card payment' : value === 'transfer' ? 'a transfer' : 'spending'} from now on`,
      )
    } catch (e) {
      console.error('Failed to update counts-as', e)
      showToast('Failed to update', { tone: 'err' })
    }
  }

  const saveCategory = async (value: string) => {
    try {
      const res = await bankingAPI.updateTransaction(transaction.id, { category: value || null })
      onChanged({ category: res.data.category })
      setEditingCategory(false)
      setAddingNew(false)
    } catch (e) {
      console.error('Failed to update category', e)
      showToast('Failed to update category', { tone: 'err' })
    }
  }

  const markRecurring = async (cadence: string) => {
    setSavingCadence(cadence)
    try {
      await analyticsAPI.markTransactionRecurring(transaction.id, cadence)
      onChanged({ is_recurring: true, is_commitment: true })
      onClose()
      showToast(`"${label}" added to your commitments`, {
        action: { label: 'View', onClick: () => navigate('/commitments') },
      })
    } catch (e) {
      console.error('Failed to mark recurring', e)
      showToast('Failed to add commitment', { tone: 'err' })
      setSavingCadence(null)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-50 min-w-0 truncate">{label}</h3>
          <div className="flex items-center gap-3 shrink-0">
            <span className={`text-lg font-semibold tnum ${isCredit ? 'text-pos' : 'text-slate-100'}`}>
              {isCredit ? '+' : '−'}{money(transaction.amount, transaction.currency)}
            </span>
            <button onClick={onClose} aria-label="Close" className="text-slate-500 hover:text-slate-200">
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
        <p className="text-sm text-slate-500 mt-0.5 mb-1">
          {dateDMY(transaction.transaction_date)} · {accountName}
          {transaction.merchant_name && transaction.description !== transaction.merchant_name && (
            <span className="text-slate-600"> · {transaction.description}</span>
          )}
        </p>
        <div className="mb-3 flex flex-wrap gap-1.5">
          {transaction.is_commitment && <span className="chip-warn">Commitment</span>}
          {transaction.is_recurring && <span className="chip-info">Recurring</span>}
          {transaction.is_financed && <span className="chip-info">On finance</span>}
        </div>
        {transaction.excluded_reason && !countsAs && (
          <p className="text-xs text-slate-500 mb-3">{EXCLUDED_COPY[transaction.excluded_reason]}</p>
        )}

        {/* Counts as — the user's word beats automatic detection everywhere
            (spending figures, the trend, the projection's surplus). */}
        {!isCredit && (
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <span className="text-xs text-slate-500">Counts as</span>
            <div className="flex gap-0.5">
              {[
                { key: 'spending', label: 'Spending' },
                { key: 'transfer', label: 'Transfer' },
                { key: 'card_payment', label: 'Card payment' },
              ].map((o) => (
                <button
                  key={o.key}
                  onClick={() => effectiveCountsAs !== o.key && saveCountsAs(o.key)}
                  className={`${effectiveCountsAs === o.key ? 'seg-active' : 'seg'} !text-xs`}
                  title={
                    o.key === 'transfer'
                      ? 'Money moving to another of your accounts or an investment platform — not consumption'
                      : o.key === 'card_payment'
                      ? 'Settles a credit card — the purchases themselves are what count'
                      : 'Real spending — include it in your figures'
                  }
                >
                  {o.label}
                </button>
              ))}
            </div>
            {countsAs ? (
              <span className="text-xs text-slate-500">
                set by you ·{' '}
                <button onClick={() => saveCountsAs(null)} className="text-accent hover:underline">
                  use automatic
                </button>
              </span>
            ) : (
              <span className="text-xs text-slate-600">automatic</span>
            )}
          </div>
        )}

        {/* Category */}
        <div className="flex items-center gap-2 mb-4 flex-wrap">
          <span className="text-xs text-slate-500">Category</span>
          {editingCategory ? (
            addingNew ? (
              <span className="flex items-center gap-1.5">
                <input
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && newCategory.trim() && saveCategory(newCategory.trim())}
                  placeholder="New category"
                  className="input !px-2 !py-1 !text-xs !rounded-lg !w-40"
                  autoFocus
                />
                <button
                  onClick={() => newCategory.trim() && saveCategory(newCategory.trim())}
                  className="btn-primary !px-2 !py-1 !text-xs !rounded-lg"
                >
                  Save
                </button>
              </span>
            ) : (
              <select
                value={category}
                onChange={(e) => {
                  if (e.target.value === '__ADD_NEW__') {
                    setAddingNew(true)
                  } else {
                    setCategory(e.target.value)
                    saveCategory(e.target.value)
                  }
                }}
                className="input !px-2 !py-1 !text-xs !rounded-lg !w-auto"
                autoFocus
              >
                <option value="">Uncategorized</option>
                {categories.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
                <option value="__ADD_NEW__">+ Add new category</option>
              </select>
            )
          ) : (
            <>
              {transaction.category ? (
                <span className="chip">{transaction.category}</span>
              ) : (
                <span className="text-xs text-slate-600">Uncategorized</span>
              )}
              <button onClick={() => setEditingCategory(true)} className="text-xs text-accent hover:underline">
                Change
              </button>
            </>
          )}
        </div>

        {/* This repeats → commitments */}
        <div className="rounded-xl border border-accent/40 bg-accent/10 p-4 mb-3">
          <div className="flex items-start gap-3">
            <Repeat className="w-4 h-4 text-accent shrink-0 mt-0.5" />
            <div className="min-w-0">
              <div className="text-sm font-medium text-accent">This repeats</div>
              <p className="text-xs text-slate-400 mt-0.5">
                Add it to your commitments so safe-to-spend and the forecast expect it.
              </p>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {CADENCES.map((c) => (
              <button
                key={c.key}
                onClick={() => markRecurring(c.key)}
                disabled={savingCadence !== null}
                className="px-3 py-1.5 rounded-full border border-accent/40 text-xs text-accent hover:bg-accent/15 transition-colors disabled:opacity-50"
              >
                {savingCadence === c.key ? 'Adding…' : c.label}
              </button>
            ))}
          </div>
        </div>

        {/* Rule */}
        <button
          onClick={onCreateRule}
          className="w-full text-left rounded-xl border border-white/10 hover:bg-white/[0.04] transition-colors p-4 mb-3 flex items-start gap-3"
        >
          <Wand2 className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
          <span className="min-w-0">
            <span className="block text-sm font-medium text-slate-100">
              Always categorise {label} like this
            </span>
            <span className="block text-xs text-slate-500 mt-0.5">
              Creates a rule and can backfill your history.
            </span>
          </span>
        </button>

        {/* Pay on finance (spending only) */}
        {!isCredit && (
          <button
            onClick={onPayOnFinance}
            className="w-full text-left rounded-xl border border-white/10 hover:bg-white/[0.04] transition-colors p-4 flex items-start gap-3"
          >
            <CreditCard className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
            <span className="min-w-0">
              <span className="block text-sm font-medium text-slate-100">Pay on finance</span>
              <span className="block text-xs text-slate-500 mt-0.5">
                Split it into a payment plan and drop it from spending.
              </span>
            </span>
          </button>
        )}
      </div>
    </div>
  )
}
