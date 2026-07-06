import { useEffect, useState } from 'react'
import { analyticsAPI, AccountSettingUpdate } from '../services/api'
import { SummaryAccount } from '../types'
import { gbp } from '../lib/format'

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
    repayment_cadence: account.repayment_cadence ?? 'end_of_month',
    repayment_day: account.repayment_day ?? undefined,
    repayment_interval_months: account.repayment_interval_months ?? undefined,
    repayment_anchor_date: account.repayment_anchor_date ?? undefined,
    repayment_strategy: account.repayment_strategy ?? 'full_balance',
    repayment_fixed_amount: account.repayment_fixed_amount ?? undefined,
    repayment_installments: account.repayment_installments ?? 3,
    pay_from_account_id: account.pay_from_account_id ?? undefined,
  })
  const [saving, setSaving] = useState(false)

  const set = (patch: Partial<AccountSettingUpdate>) => setForm((f) => ({ ...f, ...patch }))

  const save = async () => {
    setSaving(true)
    const payload: AccountSettingUpdate = { ...form }
    if (form.role === 'credit' && form.repayment_strategy === 'installments') {
      // Installments step monthly from the first-payment date.
      payload.repayment_cadence = 'every_n_months'
      payload.repayment_interval_months = 1
    }
    try {
      await analyticsAPI.updateAccountSettings(account.id, payload)
      onSaved()
    } catch (e) {
      console.error('Failed to save settings', e)
      setSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold text-slate-50 mb-1">{account.display_name}</h3>
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
          <div className="space-y-3 mb-4">
            <div>
              <label className="label">How is it repaid?</label>
              <select
                value={form.repayment_strategy ?? 'full_balance'}
                onChange={(e) => set({ repayment_strategy: e.target.value })}
                className="input"
              >
                <option value="full_balance">Pay the full balance each cycle (e.g. Amex)</option>
                <option value="fixed">Pay a fixed amount each month</option>
                <option value="installments">Pay the balance off in installments (e.g. Monzo Flex)</option>
                <option value="scheduled">Scheduled payments (set each amount &amp; date)</option>
              </select>
            </div>

            {form.repayment_strategy === 'fixed' && (
              <div>
                <label className="label">Amount paid each cycle (£)</label>
                <input
                  type="number" min={0} step="0.01"
                  value={form.repayment_fixed_amount ?? ''}
                  onChange={(e) => set({ repayment_fixed_amount: e.target.value === '' ? null : Number(e.target.value) })}
                  className="input"
                  placeholder="e.g. 200"
                />
                {account.current_balance && form.repayment_fixed_amount ? (
                  <p className="text-xs text-slate-500 mt-1">
                    {(() => {
                      const owed = Math.abs(account.current_balance)
                      const months = Math.ceil(owed / Math.max(form.repayment_fixed_amount, 1))
                      return `≈ ${months} month${months !== 1 ? 's' : ''} to clear the current ${gbp(owed)} balance`
                    })()}
                  </p>
                ) : null}
              </div>
            )}

            {(form.repayment_strategy === 'full_balance' || form.repayment_strategy === 'fixed') && (
              <>
                <div>
                  <label className="label">Repayment cycle</label>
                  <select
                    value={form.repayment_cadence ?? 'end_of_month'}
                    onChange={(e) => set({ repayment_cadence: e.target.value })}
                    className="input"
                  >
                    <option value="end_of_month">End of month</option>
                    <option value="monthly">Monthly on a day</option>
                    <option value="weekly">Weekly</option>
                  </select>
                </div>
                {form.repayment_cadence === 'monthly' && (
                  <div>
                    <label className="label">Payment day of month</label>
                    <input
                      type="number" min={1} max={31}
                      value={form.repayment_day ?? ''}
                      onChange={(e) => set({ repayment_day: e.target.value === '' ? null : Number(e.target.value) })}
                      className="input"
                    />
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
                {account.current_balance ? (
                  <p className="col-span-2 text-xs text-slate-500">
                    {gbp(Math.abs(account.current_balance) / (form.repayment_installments || 1))}{' '}
                    per month × {form.repayment_installments || 1}
                  </p>
                ) : null}
              </div>
            )}

            {form.repayment_strategy === 'scheduled' && (
              <ScheduledRepaymentsEditor accountId={account.id} />
            )}

            <div>
              <label className="label">Paid from</label>
              <select
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

        <div className="flex justify-end gap-2 mt-2">
          <button onClick={onClose} className="btn-ghost">
            Cancel
          </button>
          <button onClick={save} disabled={saving} className="btn-primary">
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
