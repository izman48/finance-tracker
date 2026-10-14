import { describe, expect, it } from 'vitest'
import { aprTyping, warningText, validateApr, type RepaymentWarning } from './repaymentWarnings'

// Repayment warnings in card settings (ux T-10-0 A.6; C-17). Synthetic values.
const w = (code: RepaymentWarning['code'], values: RepaymentWarning['values']): RepaymentWarning => ({ code, values })

describe('warningText', () => {
  it('interest with an APR gives the monthly figure, without one asks for the APR', () => {
    expect(warningText(w('interest_cost', { monthly_interest: '71.95', apr: '20.00' }), 'Test Bank')).toBe(
      "Paying less than your statement balance means Test Bank charges interest on what is left. That is about £71.95 a month at your card's APR.")
    expect(warningText(w('interest_cost', { monthly_interest: null, apr: null }), 'Test Bank')).toBe(
      "Paying less than your statement balance means Test Bank charges interest on what is left. Add the card's APR above to see the cost.")
  })

  it('late fee names the day and the due date', () => {
    expect(warningText(w('late_fee_risk', { pay_date: '2026-10-31', due_date: '2026-10-28', repayment_day: '31' }), 'Test Bank')).toBe(
      'Day 31 is after your card\'s due date of 28 Oct. Test Bank may charge a late fee. Choose "Card due date" or an earlier day.')
    expect(warningText(w('late_fee_risk', { pay_date: '2026-10-31', due_date: '2026-10-28', repayment_day: null }), 'Test Bank')).toBe(
      'Your payment on 31 Oct is after your card\'s due date of 28 Oct. Test Bank may charge a late fee. Choose "Card due date" or an earlier day.')
  })

  it('overdraft says how far the account goes, with or without a limit', () => {
    const values = { amount: '5000.00', account_name: 'Test Current', balance: '-1200.00', date: '2026-10-31' }
    expect(warningText(w('overdraft_breach', { ...values, limit: '500.00' }), 'Test Bank')).toBe(
      'This payment of £5,000.00 would take Test Current to −£1,200.00, past its overdraft limit of £500.00. Pay from another account, or move money in before 31 Oct.')
    expect(warningText(w('overdraft_breach', { ...values, limit: null }), 'Test Bank')).toBe(
      'This payment of £5,000.00 would take Test Current below £0. Pay from another account, or move money in before 31 Oct.')
  })
})

describe('validateApr', () => {
  it.each(['-1', '100.01', 'abc', '20.001'])('refuses %j', (v) => {
    expect(validateApr(v)).toBe('Enter a number from 0 to 100.')
  })
  it.each(['', '0', '19.9', '100'])('accepts %j', (v) => {
    expect(validateApr(v)).toBeNull()
  })
})

describe('aprTyping (ux nit on #189)', () => {
  it('keeps digits and one decimal point while typing', () => {
    expect(aprTyping('abc')).toBe('')
    expect(aprTyping('19.9%')).toBe('19.9')
    expect(aprTyping('1.2.3')).toBe('1.23')
  })
})
