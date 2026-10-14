/** Wording for the API's repayment warnings (ux T-10-0 A.6; T-10-5). The
 * API sends a code plus values; the text is built here from fixed templates
 * with those values inserted as text. No figures are computed here. */
import { dateDayMonth, money } from './format'

export interface RepaymentWarning {
  code: 'interest_cost' | 'late_fee_risk' | 'overdraft_breach'
  values: Record<string, string | null>
}

const pounds = (amount: string | null | undefined) => money(Number(amount))

export function warningText(warning: RepaymentWarning, providerName: string): string {
  const v = warning.values
  switch (warning.code) {
    case 'interest_cost': {
      const lead = `Paying less than your statement balance means ${providerName} charges interest on what is left.`
      return v.monthly_interest
        ? `${lead} That is about ${pounds(v.monthly_interest)} a month at your card's APR.`
        : `${lead} Add the card's APR above to see the cost.`
    }
    case 'late_fee_risk': {
      const when = v.repayment_day ? `Day ${v.repayment_day}` : `Your payment on ${dateDayMonth(v.pay_date)}`
      return `${when} is after your card's due date of ${dateDayMonth(v.due_date)}. ${providerName} may charge a late fee. Choose "Card due date" or an earlier day.`
    }
    case 'overdraft_breach': {
      const goesTo = v.limit
        ? `to −${pounds(String(Math.abs(Number(v.balance))))}, past its overdraft limit of ${pounds(v.limit)}`
        : 'below £0'
      return `This payment of ${pounds(v.amount)} would take ${v.account_name} ${goesTo}. Pay from another account, or move money in before ${dateDayMonth(v.date)}.`
    }
  }
}

const APR = /^\d{1,3}(\.\d{1,2})?$/

/** The card APR field (A2): blank, or 0 to 100 with at most 2 dp. */
export function validateApr(text: string): string | null {
  const value = text.trim()
  if (value === '') return null
  return APR.test(value) && Number(value) <= 100 ? null : 'Enter a number from 0 to 100.'
}

/** What the APR box keeps while typing: digits and one decimal point. */
export function aprTyping(text: string): string {
  const [whole, ...rest] = text.replace(/[^\d.]/g, '').split('.')
  return rest.length ? `${whole}.${rest.join('')}` : whole
}
