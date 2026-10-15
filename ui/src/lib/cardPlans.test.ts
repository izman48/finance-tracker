import { describe, expect, it } from 'vitest'
import type { CardPlan } from '../services/api'
import {
  blankPlanForm, cardPlanChips, planBody, planFormFor, plansOnCard, settingsPlanLine, standalonePlans,
  unconfirmedNotice, validatePlanForm, wealthPlanLine,
} from './cardPlans'

// Card instalment plans (T-12-7b; ux T-12-1 "Plans"; owner D3/D4). Synthetic.
const plan = (over: Partial<CardPlan> = {}): CardPlan => ({
  id: 'p1', card_account_id: 'c1', card_name: 'Harbor Rewards', name: 'Laptop plan', balance: '800.00',
  instalment: '100.00', fee: '5.00', instalments_remaining: 8, next_date: '2026-11-04', final_date: '2027-06-04',
  monthly_total: '105.00', in_net_worth: false, provider_confirmed: false, ...over,
})

describe('which plans go where', () => {
  it('plans sit under their own card; a plan whose card has gone stands alone', () => {
    const plans = [plan(), plan({ id: 'p2', card_account_id: 'c2' }), plan({ id: 'p3', card_account_id: null })]
    expect(plansOnCard(plans, 'c1').map((p) => p.id)).toEqual(['p1'])
    expect(standalonePlans(plans).map((p) => p.id)).toEqual(['p3'])
  })
})

describe('the words (ux "Plans")', () => {
  it('card settings row: monthly total, then instalment + fee, payments to go and what is left', () => {
    expect(settingsPlanLine(plan())).toBe('£100.00 instalment + £5.00 fee · 8 payments to go · £800.00 left')
  })
  it('no fee: the fee part is left out; one payment reads singular', () => {
    expect(settingsPlanLine(plan({ fee: '0.00', instalments_remaining: 1, balance: '100.00' })))
      .toBe('£100.00 instalment · 1 payment to go · £100.00 left')
  })
  it('the card row chip counts unconfirmed plans, else says what the balance includes', () => {
    expect(cardPlanChips([plan()])).toEqual({ unconfirmed: '1 plan not in net worth yet', includes: null })
    expect(cardPlanChips([plan(), plan({ id: 'p2' })]).unconfirmed).toBe('2 plans not in net worth yet')
    expect(cardPlanChips([plan({ provider_confirmed: true })])).toEqual({ unconfirmed: null, includes: 'includes 1 plan' })
    expect(cardPlanChips([])).toEqual({ unconfirmed: null, includes: null })
  })
  it('Wealth plan line: unconfirmed says why and that the payment still counts (D4)', () => {
    expect(wealthPlanLine(plan(), 'Harbor Financial')).toBe(
      "We haven't confirmed whether Harbor Financial includes plans in the card balance. £105 a month still counts in the card bill.",
    )
  })
  it('Wealth plan line: confirmed is inside the card balance', () => {
    expect(wealthPlanLine(plan({ provider_confirmed: true, monthly_total: '60.00', instalments_remaining: 7 }), 'X'))
      .toBe('£60 a month · 7 payments to go · inside the card balance')
  })
  it('the settings notice sums the unconfirmed plans on the card, and is absent when all are confirmed', () => {
    expect(unconfirmedNotice([plan(), plan({ id: 'p2', monthly_total: '20.50' })], 'Harbor Financial')).toBe(
      "Not in net worth yet: we haven't confirmed whether Harbor Financial includes plans in the card balance. " +
      'The £125.50 a month still counts in the card bill, your forecast and safe to spend.',
    )
    expect(unconfirmedNotice([plan({ provider_confirmed: true })], 'X')).toBeNull()
  })
})

describe('the plan form', () => {
  const today = '2026-10-15'
  const valid = { ...blankPlanForm(today), name: 'Laptop plan', balance: '800', instalment: '100', fee: '5', payments: '8' }

  it('a valid form has no errors and sends the typed strings', () => {
    expect(validatePlanForm(valid)).toEqual({})
    expect(planBody(valid)).toEqual({
      name: 'Laptop plan', balance: '800', instalment: '100', fee: '5',
      instalments_remaining: 8, next_date: valid.next_date,
    })
  })
  // The API doesn't return the APR, so a blank APR is left out: an edit
  // never clears one entered earlier.
  it('blank fee is sent as 0; APR only when given', () => {
    expect(planBody({ ...valid, fee: '', apr: '19.9' })).toMatchObject({ fee: '0', apr: '19.9' })
  })
  it('each field says what is wrong, in ux words', () => {
    const errors = validatePlanForm({ ...valid, name: ' ', balance: '-1', instalment: '0', fee: 'x', payments: '121', apr: '101' })
    expect(errors).toEqual({
      name: 'Give it a name.', balance: 'Enter 0 or more.', instalment: 'Enter an amount above 0.',
      fee: 'Enter 0 or more.', payments: 'Enter a whole number from 1 to 120.', apr: 'Enter a rate from 0 to 100.',
    })
  })
  it('the fee is at most £1,000 a month (sec)', () => {
    expect(validatePlanForm({ ...valid, fee: '1000.01' }).fee).toBe('Enter an amount from 0 to 1,000.')
    expect(validatePlanForm({ ...valid, fee: '1000' }).fee).toBeUndefined()
  })
  it('payments left must be whole', () => {
    expect(validatePlanForm({ ...valid, payments: '2.5' }).payments).toBe('Enter a whole number from 1 to 120.')
  })
  it('the edit form starts from the stored plan', () => {
    expect(planFormFor(plan())).toMatchObject({ name: 'Laptop plan', balance: '800.00', instalment: '100.00', fee: '5.00', payments: '8', next_date: '2026-11-04' })
  })
})
