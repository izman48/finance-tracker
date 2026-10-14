import type { AccountSettingUpdate } from '../services/api'

/** Fields that only mean something on a credit card. The API refuses them
 * (422) on any other role (T-10-4a), so they are left out of the request. */
const REPAYMENT_FIELDS = [
  'repayment_cadence',
  'repayment_interval_months',
  'repayment_day',
  'repayment_anchor_date',
  'repayment_strategy',
  'repayment_fixed_amount',
  'repayment_installments',
  'pay_from_account_id',
  'instalment_card',
] as const

/** The request body for saving the account settings form. */
export function settingsPayload(form: AccountSettingUpdate): AccountSettingUpdate {
  const payload: AccountSettingUpdate = { ...form }
  if (form.role !== 'credit') {
    for (const field of REPAYMENT_FIELDS) delete payload[field]
    return payload
  }
  if (form.repayment_strategy === 'installments') {
    // Installments step monthly from the first-payment date.
    payload.repayment_cadence = 'every_n_months'
    payload.repayment_interval_months = 1
  }
  return payload
}
