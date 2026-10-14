import { useCallback, useEffect, useState } from 'react'
import { analyticsAPI, AccountSettingUpdate, type CardStatements } from '../services/api'
import { SummaryAccount } from '../types'
import { gbp } from '../lib/format'
import {
  initialRepayment, payDayOptions, saveErrorMessage, settingsPayload, strategyOptions, validateRepayment,
} from '../lib/accountSettings'
import StatementBlock from './card/StatementBlock'

// Help under "How is it repaid?" (ux A.5).
const STRATEGY_HELP: Record<string, string> = {
  statement_balance: 'Pays what your latest statement says, on its due date. Spending since goes on the next bill.',
  full_balance: 'Pays everything you owe at the time, including spending since the statement.',
}
// Strategies that pay on a pay day (instalments and scheduled set their own dates).
const PAY_DAY_STRATEGIES = new Set(['statement_balance', 'full_balance', 'fixed', 'minimum_percent'])

export default function AccountSettingsModal({
  account,
  spendingAccounts,
  onClose,
  onSaved,
}: {
  account: SummaryAccount
  spendingAccounts: SummaryAccount[]
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState<AccountSettingUpdate>({
    role: account.role,
    overdraft_limit: account.overdraft_limit ?? undefined,
    repayment_day: account.repayment_day ?? undefined,
    repayment_interval_months: account.repayment_interval_months ?? undefined,
    repayment_anchor_date: account.repayment_anchor_date ?? undefined,
    repayment_fixed_amount: account.repayment_fixed_amount ?? undefined,
    repayment_installments: account.repayment_installments ?? 3,
    pay_from_account_id: account.pay_from_account_id ?? undefined,
    ...initialRepayment(account),
  })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [dayError, setDayError] = useState<string | null>(null)
  // Whether the card has a statement, for the "Card due date" help text.
  const [hasDueDate, setHasDueDate] = useState(false)
  const onStatementsLoaded = useCallback((data: CardStatements) => setHasDueDate(data.current !== null), [])
  // The statement load said this card isn't the user's (404): nothing to save (C-21).
  const [cardMissing, setCardMissing] = useState(false)
  const onCardMissing = useCallback(() => setCardMissing(true), [])
  // Money owed, positive on every provider (the server normalises the sign).
  const owed = Number(account.credit_owed ?? 0)

  const set = (patch: Partial<AccountSettingUpdate>) => setForm((f) => ({ ...f, ...patch }))

  const save = async () => {
    const invalid = validateRepayment(form)
    setDayError(invalid.repayment_day ?? null)
    if (invalid.repayment_day) return
    setSaving(true)
    setSaveError(null)
    try {
      await analyticsAPI.updateAccountSettings(account.id, settingsPayload(form))
      onSaved()
    } catch (e) {
      setSaveError(saveErrorMessage(e, form.repayment_strategy))
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={`modal-panel${form.role === 'credit' ? ' !max-w-lg' : ''}`} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="account-settings-title"
      >
        <h3 id="account-settings-title" className="text-lg font-semibold text-slate-50 mb-1">{account.display_name}</h3>
        <p className="text-sm text-slate-400 mb-4">Configure how this account is treated.</p>

        <label className="label">Role</label>
        <select
          value={form.role}
          onChange={(e) => set({ role: e.target.value })}
          className="input mb-4"
        >
          <option value="spending">Spending (counts in safe-to-spend)</option>
          <option value="savings">Savings (earmarked)</option>
          <option value="credit">Credit card (owed, repaid on schedule)</option>
          <option value="excluded">Excluded</option>
        </select>

        {form.role === 'spending' && (
          <div className="mb-4">
            <label className="label">Overdraft limit (£)</label>
            <input
              type="number"
              value={form.overdraft_limit ?? ''}
              onChange={(e) => set({ overdraft_limit: e.target.value === '' ? null : Number(e.target.value) })}
              className="input"
              placeholder="0"
            />
          </div>
        )}

        {form.role === 'credit' && (
          <StatementBlock
            accountId={account.id}
            savedAsCredit={account.role === 'credit'}
            currentBalance={String(account.credit_owed ?? 0)}
            providerName={account.provider_name}
            onNotFound={onCardMissing}
            onLoaded={onStatementsLoaded}
          />
        )}

        {form.role === 'credit' && (
          <div className="space-y-3 mb-4">
            {account.repayment_fix_needed && (
              <div className="banner-info">
                This card uses scheduled payments, which are meant for instalment cards like Monzo Flex. Nothing has
                changed. Choose how this card is repaid, or tick "This is an instalment card" if it is one.
              </div>
            )}
            <div>
              <label htmlFor="repayment-strategy" className="label">How is it repaid?</label>
              <select
                id="repayment-strategy"
                value={form.repayment_strategy ?? 'statement_balance'}
                onChange={(e) => set({ repayment_strategy: e.target.value })}
                aria-describedby="repayment-strategy-help"
                className="input"
              >
                {strategyOptions(account.repayment_strategy, Boolean(form.instalment_card), form.repayment_strategy).map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <p id="repayment-strategy-help" className="text-xs text-slate-400 mt-1">
                {STRATEGY_HELP[form.repayment_strategy ?? ''] ?? ''}
              </p>
            </div>

            <label htmlFor="instalment-card" className="flex items-center gap-2 text-sm text-slate-300 min-h-[44px]">
              <input
                id="instalment-card"
                type="checkbox"
                checked={Boolean(form.instalment_card)}
                onChange={(e) => set({ instalment_card: e.target.checked })}
              />
              This is an instalment card, like Monzo Flex
            </label>

            {form.repayment_strategy === 'fixed' && (
              <div>
                <label htmlFor="repayment-amount" className="label">Amount paid each cycle (£)</label>
                <input
                  id="repayment-amount"
                  type="number" min={0} step="0.01"
                  value={form.repayment_fixed_amount ?? ''}
                  onChange={(e) => set({ repayment_fixed_amount: e.target.value === '' ? null : Number(e.target.value) })}
                  className="input"
                  placeholder="e.g. 200"
                />
                {owed > 0 && form.repayment_fixed_amount ? (
                  <p className="text-xs text-slate-500 mt-1">
                    {(() => {
                      const months = Math.ceil(owed / Math.max(form.repayment_fixed_amount, 1))
                      return `≈ ${months} month${months !== 1 ? 's' : ''} to clear the current ${gbp(owed)} balance`
                    })()}
                  </p>
                ) : null}
              </div>
            )}

            {form.repayment_strategy === 'minimum_percent' && (
              <div>
                <label htmlFor="repayment-percent" className="label">Percent of the current balance (%)</label>
                <input
                  id="repayment-percent"
                  type="number" min={1} max={100}
                  value={form.repayment_fixed_amount ?? ''}
                  onChange={(e) => set({ repayment_fixed_amount: e.target.value === '' ? null : Number(e.target.value) })}
                  className="input"
                />
              </div>
            )}

            {PAY_DAY_STRATEGIES.has(form.repayment_strategy ?? '') && (
              <>
                <div>
                  <label htmlFor="repayment-pay-day" className="label">Pay day</label>
                  <select
                    id="repayment-pay-day"
                    value={form.repayment_cadence ?? 'card_due_date'}
                    onChange={(e) => set({ repayment_cadence: e.target.value })}
                    aria-describedby="repayment-pay-day-help"
                    className="input"
                  >
                    {payDayOptions(account.repayment_cadence).map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  {form.repayment_cadence === 'card_due_date' && (
                    <p id="repayment-pay-day-help" className="text-xs text-slate-400 mt-1">
                      {hasDueDate
                        ? 'Uses the due date on your statement.'
                        : "No due date yet. nilu uses the card's usual payment date, or 30 days from today."}
                    </p>
                  )}
                </div>
                {form.repayment_cadence === 'monthly' && (
                  <div>
                    <label htmlFor="repayment-day" className="label">Day (1 to 31)</label>
                    <input
                      id="repayment-day"
                      type="number" min={1} max={31}
                      value={form.repayment_day ?? ''}
                      onChange={(e) => set({ repayment_day: e.target.value === '' ? null : Number(e.target.value) })}
                      aria-invalid={dayError ? true : undefined}
                      aria-describedby={dayError ? 'repayment-day-error' : undefined}
                      className="input"
                    />
                    {dayError && <p id="repayment-day-error" className="text-xs text-neg mt-1">{dayError}</p>}
                  </div>
                )}
              </>
            )}

            {form.repayment_strategy === 'installments' && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">Number of payments</label>
                  <input
                    type="number" min={1}
                    value={form.repayment_installments ?? 3}
                    onChange={(e) => set({ repayment_installments: Number(e.target.value) })}
                    className="input"
                  />
                </div>
                <div>
                  <label className="label">First payment</label>
                  <input
                    type="date"
                    value={form.repayment_anchor_date ?? ''}
                    onChange={(e) => set({ repayment_anchor_date: e.target.value || null })}
                    className="input"
                  />
                </div>
                {owed > 0 ? (
                  <p className="col-span-2 text-xs text-slate-500">
                    {gbp(owed / (form.repayment_installments || 1))}{' '}
                    per month × {form.repayment_installments || 1}
                  </p>
                ) : null}
              </div>
            )}

            {form.repayment_strategy === 'scheduled' && (
              <ScheduledRepaymentsEditor accountId={account.id} />
            )}

            <div>
              <label htmlFor="repayment-pay-from" className="label">Paid from</label>
              <select
                id="repayment-pay-from"
                value={form.pay_from_account_id ?? ''}
                onChange={(e) => set({ pay_from_account_id: e.target.value || null })}
                className="input"
              >
                <option value="">—</option>
                {spendingAccounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.display_name}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {saveError && <div role="alert" className="banner-err mb-3">{saveError}</div>}

        <div className="flex justify-end gap-2 mt-2">
          <button onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button onClick={save} disabled={saving || cardMissing} className="btn-primary">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

interface RepaymentItem {
  id: string
  due_date: string
  amount: number
}

// Editor for the `scheduled` repayment strategy: a list of explicit
// date+amount payments the user intends to make. Each add/remove hits the API
// immediately (they belong to the account, not the settings form being saved).
function ScheduledRepaymentsEditor({ accountId }: { accountId: string }) {
  const [items, setItems] = useState<RepaymentItem[]>([])
  const [date, setDate] = useState('')
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    try {
      const res = await analyticsAPI.getRepayments(accountId)
      setItems(res.data.map((r: RepaymentItem) => ({ ...r, amount: Number(r.amount) })))
    } catch (e) {
      console.error('Failed to load scheduled repayments', e)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId])

  const add = async () => {
    if (!date || !amount || Number(amount) <= 0) return
    setBusy(true)
    try {
      await analyticsAPI.addRepayment(accountId, { due_date: date, amount: Number(amount) })
      setDate('')
      setAmount('')
      await load()
    } catch (e) {
      console.error('Failed to add repayment', e)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id: string) => {
    setBusy(true)
    try {
      await analyticsAPI.deleteRepayment(accountId, id)
      setItems((xs) => xs.filter((x) => x.id !== id))
    } catch (e) {
      console.error('Failed to remove repayment', e)
    } finally {
      setBusy(false)
    }
  }

  const total = items.reduce((s, x) => s + x.amount, 0)

  return (
    <div>
      <label className="label">Scheduled payments</label>
      {items.length > 0 ? (
        <ul className="space-y-1.5 mb-2">
          {items.map((it) => (
            <li key={it.id} className="flex items-center gap-2 text-sm">
              <span className="text-slate-300 tnum">
                {new Date(it.due_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
              </span>
              <span className="ml-auto text-slate-100 tnum">{gbp(it.amount)}</span>
              <button
                onClick={() => remove(it.id)}
                disabled={busy}
                className="text-slate-500 hover:text-neg transition-colors"
                aria-label="Remove payment"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-slate-500 mb-2">No payments scheduled yet.</p>
      )}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="input" />
        </div>
        <div className="flex-1">
          <input
            type="number" min={0} step="0.01" placeholder="£ amount"
            value={amount} onChange={(e) => setAmount(e.target.value)} className="input"
          />
        </div>
        <button onClick={add} disabled={busy || !date || !amount} className="btn-ghost shrink-0">
          Add
        </button>
      </div>
      {items.length > 0 && (
        <p className="text-xs text-slate-500 mt-1">
          {items.length} payment{items.length !== 1 ? 's' : ''} · {gbp(total)} total scheduled
        </p>
      )}
    </div>
  )
}
