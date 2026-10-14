import { describe, expect, it } from 'vitest'
import { cardStatementLine } from './cardStatement'
import { dateDayMonth } from './format'

// ux T-10-13 "Words": card row line 2, in order of precedence (G-4).
// Synthetic fixture: statement £5,000.00 due 31 Oct.
const due = '2026-10-31'
const statement = (over = {}) => ({ statement_balance: '5000.00', due_date: due, paid: false, missing: false, ...over })

describe('cardStatementLine', () => {
  it('unpaid statement: amount and due date', () => {
    expect(cardStatementLine(statement())).toEqual({ text: `Statement £5,000.00 · due ${dateDayMonth(due)}`, withProvider: true })
  })

  it('paid: "Statement paid" with a Paid chip', () => {
    expect(cardStatementLine(statement({ paid: true }))).toEqual({ text: 'Statement paid', chip: 'Paid', withProvider: true })
  })

  it('due date passed with no newer statement: "Statement was due …" and an Add new action', () => {
    expect(cardStatementLine(statement({ missing: true }))).toEqual({ text: `Statement was due ${dateDayMonth(due)}`, action: 'Add new' })
  })

  it('a card with no statement entered (null): an Add statement action', () => {
    expect(cardStatementLine(null)).toEqual({ text: null, action: 'Add statement' })
  })

  it('no statement data in the response (key absent): nothing, the provider shows alone', () => {
    expect(cardStatementLine(undefined)).toEqual({ text: null })
  })

  it('missing wins over paid (the due date passed, a newer statement is needed)', () => {
    expect(cardStatementLine(statement({ paid: true, missing: true })).action).toBe('Add new')
  })
})
