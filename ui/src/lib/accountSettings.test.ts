import { describe, expect, it } from 'vitest'
import { settingsPayload } from './accountSettings'
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
