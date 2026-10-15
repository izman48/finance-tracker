import { useCallback, useEffect, useState } from 'react'
import { cardPlansAPI, type CardPlan } from '../../services/api'
import {
  blankPlanForm, planBody, planFormFor, plansOnCard, settingsPlanLine, unconfirmedNotice, validatePlanForm,
  type PlanErrors, type PlanFormState,
} from '../../lib/cardPlans'
import { apiToday } from '../../lib/statements'
import { gbp } from '../../lib/format'
import Sheet from '../ui/Sheet'
import { useConfirm } from '../ui/ConfirmDialog'
import { useToast } from '../ui/Toast'
import PlanForm from './PlanForm'

const focusLater = (id: string) => window.setTimeout(() => document.getElementById(id)?.focus(), 0)

/** What the block shows (tested as markup): the card's plans, the D4 notice
 *  when its provider isn't confirmed, and the actions in keyboard order. */
export function InstalmentPlansView({ plans, provider, failed, onAdd, onEdit, onRemove, onRetry }: {
  plans: CardPlan[]
  provider: string
  failed: boolean
  onAdd: () => void
  onEdit: (p: CardPlan) => void
  onRemove: (p: CardPlan) => void
  onRetry: () => void
}) {
  const notice = unconfirmedNotice(plans, provider)
  return (
    <section aria-labelledby="instalment-plans-title" className="mb-4">
      <h4 id="instalment-plans-title" className="text-sm font-medium text-slate-200 mb-1">Instalment plans</h4>
      <p className="text-xs text-slate-400 mb-2">Plan purchases stay out of your budgets. The monthly payment is part of the card bill.</p>
      {failed ? (
        <div className="banner-err flex flex-wrap items-center gap-3" role="alert">
          <span className="flex-1 min-w-0">We could not load your plans.</span>
          <button type="button" className="btn-ghost" onClick={onRetry}>Try again</button>
        </div>
      ) : (
        <>
          {notice && <div className="banner-info mb-2 !text-xs text-amber-200">{notice}</div>}
          {plans.length > 0 && (
            <ul className="divide-y divide-white/[0.06] mb-2">
              {plans.map((p) => (
                <li key={p.id} className="py-2">
                  <div className="flex items-baseline gap-2">
                    <span className="flex-1 min-w-0 text-sm text-slate-100 truncate">{p.name}</span>
                    <span className="text-sm tnum text-slate-200">{gbp(Number(p.monthly_total))} a month</span>
                  </div>
                  <div className="text-xs text-slate-400">{settingsPlanLine(p)}</div>
                  <div className="flex gap-3 mt-1">
                    <button type="button" id={`plan-edit-${p.id}`} aria-label={`Edit ${p.name}`} onClick={() => onEdit(p)}
                      className="text-xs text-accent underline min-h-[44px] sm:min-h-0">Edit</button>
                    <button type="button" id={`plan-remove-${p.id}`} aria-label={`Remove ${p.name}`} onClick={() => onRemove(p)}
                      className="text-xs text-accent underline min-h-[44px] sm:min-h-0">Remove</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <button type="button" id="plan-add" onClick={onAdd} className="btn-ghost min-h-[44px] sm:min-h-0">Add a plan</button>
        </>
      )}
    </section>
  )
}

type Editing = { mode: 'add' } | { mode: 'edit'; plan: CardPlan }

/** The Instalment plans block in card settings (T-12-7b): loads the card's
 *  plans and adds, edits and removes them. Copy and checks live in
 *  lib/cardPlans; the server's answer is the authority. */
export default function InstalmentPlans({ cardId, provider, onChanged }: {
  cardId: string
  provider: string
  onChanged?: () => void
}) {
  const [plans, setPlans] = useState<CardPlan[]>([])
  const [failed, setFailed] = useState(false)
  const [editing, setEditing] = useState<Editing | null>(null)
  const [form, setForm] = useState<PlanFormState>(blankPlanForm(apiToday()))
  const [errors, setErrors] = useState<PlanErrors>({})
  const [saving, setSaving] = useState(false)
  const confirm = useConfirm()
  const toast = useToast()

  const load = useCallback(() => {
    cardPlansAPI.list()
      .then((res) => { setPlans(plansOnCard(res.data, cardId)); setFailed(false) })
      .catch(() => setFailed(true))
  }, [cardId])
  useEffect(load, [load])

  const open = (next: Editing) => {
    setEditing(next)
    setErrors({})
    setForm(next.mode === 'edit' ? planFormFor(next.plan) : blankPlanForm(apiToday()))
  }
  const close = () => {
    const back = editing?.mode === 'edit' ? `plan-edit-${editing.plan.id}` : 'plan-add'
    setEditing(null)
    focusLater(back)
  }

  const save = async () => {
    const found = validatePlanForm(form)
    setErrors(found)
    if (Object.keys(found).length > 0 || !editing) return
    setSaving(true)
    try {
      const terms = planBody(form)
      if (editing.mode === 'add') await cardPlansAPI.create({ card_account_id: cardId, ...terms })
      else await cardPlansAPI.update(editing.plan.id, terms)
      setEditing(null)
      focusLater('plan-add')
      load()
      onChanged?.()
    } catch (e: any) {
      if (e?.message !== 'anonymized-write-blocked') toast('We could not save this plan. Nothing was changed. Try again.', { tone: 'err' })
    } finally {
      setSaving(false)
    }
  }

  const remove = async (p: CardPlan) => {
    const ok = await confirm({
      title: `Remove ${p.name}?`, body: 'The card balance does not change. The monthly payment leaves the card bill.',
      confirmLabel: 'Remove', danger: true,
    })
    if (!ok) return focusLater(`plan-remove-${p.id}`)
    try {
      await cardPlansAPI.remove(p.id)
      focusLater('plan-add')
      load()
      onChanged?.()
    } catch (e: any) {
      if (e?.message !== 'anonymized-write-blocked') toast('We could not remove this plan. Try again.', { tone: 'err' })
    }
  }

  return (
    <>
      <InstalmentPlansView plans={plans} provider={provider} failed={failed} onAdd={() => open({ mode: 'add' })}
        onEdit={(p) => open({ mode: 'edit', plan: p })} onRemove={remove} onRetry={load} />
      {editing && (
        <Sheet title={editing.mode === 'add' ? 'Add a plan' : 'Edit plan'} onClose={close}>
          <PlanForm value={form} errors={errors} saving={saving}
            onChange={(patch) => setForm((f) => ({ ...f, ...patch }))} onCancel={close} onSave={save} />
        </Sheet>
      )}
    </>
  )
}
