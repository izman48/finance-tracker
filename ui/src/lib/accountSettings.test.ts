import { describe, expect, it } from 'vitest'
import { initialRepayment, payDayOptions, saveErrorMessage, settingsPayload, strategyOptions, validateRepayment } from './accountSettings'
import type { AccountSettingUpdate } from '../services/api'

// T-10-4a: the API refuses repayment fields on an account that isn't credit,
// so the form sends them only for a credit card.
const form: AccountSettingUpdate = {
  role: 'credit',
  overdraft_limit: 500,
  repayment_cadence: 'end_of_month',
  repayment_strategy: 'full_balance',
  repayment_installments: 3,
  repayment_day: 5,
  pay_from_account_id: 'acc-1',
}

describe('settingsPayload', () => {
  it('sends the repayment settings for a credit card', () => {
    expect(settingsPayload(form)).toEqual(form)
  })

  it.each(['spending', 'savings', 'excluded'])('sends no repayment fields for a %s account', (role) => {
    expect(settingsPayload({ ...form, role })).toEqual({ role, overdraft_limit: 500 })
  })

  it('steps instalments monthly from the first payment date', () => {
    const payload = settingsPayload({ ...form, repayment_strategy: 'installments' })
    expect(payload.repayment_cadence).toBe('every_n_months')
    expect(payload.repayment_interval_months).toBe(1)
  })
})

describe('repayment controls (T-10-6b, ux A.5; lead: existing strategies only)', () => {
  const values = (opts: { value: string }[]) => opts.map((o) => o.value)

  it('lists statement balance first and scheduled only for an instalment card or a card already on it (C-16)', () => {
    expect(values(strategyOptions('full_balance', false))).toEqual(['statement_balance', 'full_balance', 'fixed', 'installments'])
    expect(values(strategyOptions('full_balance', true))).toContain('scheduled')
    expect(values(strategyOptions('scheduled', false))).toContain('scheduled')
    expect(strategyOptions('full_balance', false)[0].label).toBe('Statement balance (default)')
  })

  it('keeps Scheduled listed while it is the selected value, so the select never shows a different option than the one saved', () => {
    expect(values(strategyOptions('full_balance', false, 'scheduled'))).toContain('scheduled')
    expect(values(strategyOptions('full_balance', false, 'fixed'))).not.toContain('scheduled')
  })

  it('keeps a stored percent-of-balance strategy visible, and only then', () => {
    expect(values(strategyOptions('minimum_percent', false))).toContain('minimum_percent')
    expect(values(strategyOptions('full_balance', false))).not.toContain('minimum_percent')
  })

  it('lists card due date and a day of the month; end of month and weekly only when already stored', () => {
    expect(values(payDayOptions('card_due_date'))).toEqual(['card_due_date', 'monthly'])
    expect(values(payDayOptions('end_of_month'))).toEqual(['card_due_date', 'monthly', 'end_of_month'])
    expect(values(payDayOptions('weekly'))).toEqual(['card_due_date', 'monthly', 'weekly'])
    expect(payDayOptions(null)[0].label).toBe('Card due date (default)')
  })

  it('C-13: a card with nothing stored starts on statement balance and the card due date; a stored value is kept', () => {
    const blank = { repayment_strategy: null, repayment_cadence: null, instalment_card: undefined }
    expect(initialRepayment(blank)).toMatchObject({ repayment_strategy: 'statement_balance', repayment_cadence: 'card_due_date', instalment_card: false })
    expect(initialRepayment({ ...blank, repayment_strategy: 'full_balance', repayment_cadence: 'end_of_month' }))
      .toMatchObject({ repayment_strategy: 'full_balance', repayment_cadence: 'end_of_month' })
  })

  it('C-15: a day of the month must be 1 to 31', () => {
    const base = { role: 'credit', repayment_strategy: 'statement_balance', repayment_cadence: 'monthly' }
    expect(validateRepayment({ ...base, repayment_day: 0 })).toEqual({ repayment_day: 'Enter a day from 1 to 31.' })
    expect(validateRepayment({ ...base, repayment_day: 32 })).toEqual({ repayment_day: 'Enter a day from 1 to 31.' })
    expect(validateRepayment({ ...base, repayment_day: null })).toEqual({ repayment_day: 'Enter a day from 1 to 31.' })
    expect(validateRepayment({ ...base, repayment_day: 28 })).toEqual({})
    expect(validateRepayment({ ...base, repayment_cadence: 'card_due_date', repayment_day: null })).toEqual({})
    expect(validateRepayment({ role: 'spending', repayment_cadence: 'monthly', repayment_day: 0 })).toEqual({})
  })

  it('reads a 422 on a switch to scheduled as the instalment-card rule, anything else as nothing changed', () => {
    const e422 = { response: { status: 422 } }
    expect(saveErrorMessage(e422, 'scheduled')).toBe(
      'Scheduled payments are only for instalment cards. Tick "This is an instalment card" to use them, or choose another option.')
    expect(saveErrorMessage(e422, 'full_balance')).toBe(
      'We could not save these settings. Nothing was changed. Check your connection and try again.')
    expect(saveErrorMessage(new Error('offline'), 'scheduled')).toBe(
      'We could not save these settings. Nothing was changed. Check your connection and try again.')
  })
})
