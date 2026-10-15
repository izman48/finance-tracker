import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { CardPlan } from '../../services/api'
import { InstalmentPlansView } from './InstalmentPlans'
import PlanForm from './PlanForm'
import { blankPlanForm } from '../../lib/cardPlans'

// The Instalment plans block in card settings and its form (ux T-12-1 "Plans",
// keyboard path). Static markup like the other component tests. Synthetic.
const plan = (over: Partial<CardPlan> = {}): CardPlan => ({
  id: 'p1', card_account_id: 'c1', card_name: 'Harbor Rewards', name: 'Laptop plan', balance: '800.00',
  instalment: '100.00', fee: '5.00', instalments_remaining: 8, next_date: '2026-11-04', final_date: '2027-06-04',
  monthly_total: '105.00', in_net_worth: false, provider_confirmed: false, ...over,
})
const noop = () => {}
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()
const view = (plans: CardPlan[], failed = false) => renderToStaticMarkup(
  <InstalmentPlansView plans={plans} provider="Harbor Financial" failed={failed} onAdd={noop} onEdit={noop} onRemove={noop} onRetry={noop} />,
)

describe('Instalment plans block', () => {
  it('no plans: the heading, the help and Add a plan only', () => {
    const t = text(view([]))
    expect(t).toContain('Instalment plans')
    expect(t).toContain('Plan purchases stay out of your budgets. The monthly payment is part of the card bill.')
    expect(t).toContain('Add a plan')
    expect(t).not.toContain('Not in net worth yet')
  })
  it('a plan row: name, monthly total, line 2, then Edit and Remove named for the plan, then Add a plan', () => {
    const h = view([plan()])
    expect(text(h)).toMatch(/Laptop plan £105\.00 a month £100\.00 instalment \+ £5\.00 fee · 8 payments to go · £800\.00 left Edit Remove .*Add a plan/)
    expect(h).toContain('aria-label="Edit Laptop plan"')
    expect(h).toContain('aria-label="Remove Laptop plan"')
  })
  it('an unconfirmed provider: the D4 notice with the monthly figure', () => {
    expect(text(view([plan()]))).toContain(
      "Not in net worth yet: we haven't confirmed whether Harbor Financial includes plans in the card balance. The £105.00 a month still counts in the card bill, your forecast and safe to spend.",
    )
  })
  it('a failed load says so with Try again, and offers no Add', () => {
    const t = text(view([], true))
    expect(t).toContain('We could not load your plans.')
    expect(t).toContain('Try again')
    expect(t).not.toContain('Add a plan')
  })
})

describe('Plan form', () => {
  const form = (errors = {}) => renderToStaticMarkup(
    <PlanForm value={blankPlanForm('2026-10-15')} errors={errors} saving={false} onChange={noop} onCancel={noop} onSave={noop} />,
  )
  it('the ux labels in order, then Cancel and Save plan', () => {
    expect(text(form())).toMatch(
      /Name .*Left to pay \(£\) .*Monthly instalment \(£\) .*Monthly fee \(£\), optional .*Payments left .*Next payment date .*Interest rate \(% APR\), optional .*Cancel .*Save plan/,
    )
  })
  it('an error is tied to its field', () => {
    const h = form({ name: 'Give it a name.' })
    expect(h).toMatch(/id="plan-name"[^>]*aria-invalid="true"[^>]*aria-describedby="plan-name-error"|aria-invalid="true"[^>]*aria-describedby="plan-name-error"[^>]*id="plan-name"/)
    expect(h).toMatch(/id="plan-name-error"[^>]*>Give it a name\./)
  })
})
