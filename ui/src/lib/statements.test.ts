import { describe, expect, it } from 'vitest'
import { statementSentence } from './statements'
import type { CardStatements } from '../services/api'

// Card statement block (ux T-10-0 A.2-A.4; T-10-6). Synthetic fixture:
// statement £5,000.00, current balance £6,000.00, unbilled £1,000.00.
const data = (over: Partial<CardStatements> = {}, current: Partial<CardStatements['current'] & object> = {}): CardStatements => ({
  statements: [],
  current: {
    statement_id: 's1', source: 'manual', statement_balance: '5000.00', statement_date: '2026-09-30',
    due_date: '2026-10-31', minimum_due: null, payments_since_statement: '0', amount_still_due: '5000.00',
    unbilled: '1000.00', paid: false, ...current,
  },
  missing_statement: false,
  conflict: false,
  next_payment: { amount: '5000.00', date: '2026-10-31', from_account_name: 'Test Current' },
  ...over,
})

describe('statementSentence (C-2, C-10)', () => {
  it('says what nilu will pay, when, from where, and where the spend since goes', () => {
    expect(statementSentence(data())).toBe(
      'nilu will pay £5,000.00 on 31 Oct 2026 from Test Current. The £1,000.00 spent since goes on your next bill.',
    )
  })

  it('drops the next-bill half when nothing was spent since', () => {
    expect(statementSentence(data({}, { unbilled: '0.00' }))).toBe('nilu will pay £5,000.00 on 31 Oct 2026 from Test Current.')
  })

  it('is absent without next_payment', () => {
    expect(statementSentence(data({ next_payment: null }))).toBeNull()
  })

  it('says the statement is paid when nothing is still due', () => {
    expect(statementSentence(data({}, { amount_still_due: '0', paid: true }))).toBe(
      'This statement is paid. The £1,000.00 spent since goes on your next bill.',
    )
  })

  it('leaves out the account when the pay-from account is unknown', () => {
    const d = data({ next_payment: { amount: '5000.00', date: '2026-10-31', from_account_name: null } })
    expect(statementSentence(d)).toMatch(/^nilu will pay £5,000\.00 on 31 Oct 2026\. /)
  })
})
