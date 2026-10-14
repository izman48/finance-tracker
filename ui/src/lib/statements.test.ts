import { describe, expect, it, vi } from 'vitest'
import {
  editFormFor,
  errorSummary,
  manualFor,
  pickStatement,
  removeStatement,
  saveStatement,
  statementBody,
  statementSentence,
  validateStatementForm,
  apiToday,
  type StatementForm,
} from './statements'
import type { CardStatements } from '../services/api'

// Card statement block (ux T-10-0 A.2-A.4; T-10-6). Synthetic fixture:
// statement £5,000.00, current balance £6,000.00, unbilled £1,000.00.
const TODAY = '2026-10-14'
const valid: StatementForm = {
  statement_balance: '5000.00', statement_date: '2026-09-30', due_date: '2026-10-31', minimum_due: '',
}

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

describe('validateStatementForm (C-4, C-5)', () => {
  it.each(['0', '-5', 'abc', '', '5000.001', '1000000.01'])('refuses a statement balance of %j', (v) => {
    expect(validateStatementForm({ ...valid, statement_balance: v }, TODAY)).toEqual({
      statement_balance: 'Enter an amount above £0 and up to £1,000,000, like 5584.00.',
    })
  })

  it('accepts the limits', () => {
    expect(validateStatementForm({ ...valid, statement_balance: '1000000', minimum_due: '0.01' }, TODAY)).toEqual({})
  })

  it('refuses a future statement date', () => {
    expect(validateStatementForm({ ...valid, statement_date: '2026-10-15', due_date: '2026-10-31' }, TODAY))
      .toEqual({ statement_date: "The statement date can't be in the future." })
  })

  it.each(['2026-09-29', '2026-11-30'])('refuses a due date of %j', (due) => {
    expect(validateStatementForm({ ...valid, due_date: due }, TODAY)).toEqual({
      due_date: 'The due date must be on or after the statement date, and no more than 60 days after it.',
    })
  })

  it('ux on #184: a blank date asks for the date, not the future or 60-day rule', () => {
    expect(validateStatementForm({ ...valid, statement_date: '' }, TODAY)).toEqual({
      statement_date: 'Enter the date on your statement.',
    })
    expect(validateStatementForm({ ...valid, due_date: '' }, TODAY)).toEqual({
      due_date: 'Enter the due date on your statement.',
    })
  })

  it('eng-b on #184: mirrors the API on a minimum above the balance and a date over 400 days old', () => {
    expect(validateStatementForm({ ...valid, minimum_due: '5000.01' }, TODAY)).toEqual({
      minimum_due: "The minimum payment can't be more than the statement balance.",
    })
    const old = { ...valid, statement_date: '2025-09-01', due_date: '2025-09-25' }
    expect(validateStatementForm(old, TODAY)).toEqual({
      statement_date: "The statement date can't be more than 400 days ago.",
    })
    // An old statement stays editable while its date is unchanged (as the API).
    expect(validateStatementForm(old, TODAY, '2025-09-01')).toEqual({})
  })

  it("uses the API's day (UTC), so the client never passes a date the API refuses", () => {
    expect(apiToday(new Date('2026-10-14T23:30:00Z'))).toBe('2026-10-14')
  })

  it('refuses a bad minimum, but a blank one is fine', () => {
    expect(validateStatementForm({ ...valid, minimum_due: '0' }, TODAY)).toEqual({
      minimum_due: 'Enter an amount above £0, or leave this blank.',
    })
    expect(validateStatementForm(valid, TODAY)).toEqual({})
  })

  it('counts the fields to fix', () => {
    expect(errorSummary(2)).toBe('Fix the 2 fields below, then save again.')
    expect(errorSummary(1)).toBe('Fix the 1 field below, then save again.')
  })
})

describe('statementBody', () => {
  it('sends every field, a blank minimum as null (sec: nothing is filled from another row)', () => {
    expect(statementBody(valid)).toEqual({
      statement_balance: '5000.00', statement_date: '2026-09-30', due_date: '2026-10-31', minimum_due: null,
    })
  })
})

const client = () => ({
  addStatement: vi.fn().mockResolvedValue({ data: { id: 'new' } }),
  updateStatement: vi.fn().mockResolvedValue({ data: { id: 's1' } }),
  deleteStatement: vi.fn().mockResolvedValue({}),
  useStatement: vi.fn().mockResolvedValue({}),
})
const httpError = (status: number) => Object.assign(new Error('x'), { response: { status } })

describe('saveStatement (C-4..C-8)', () => {
  it('sends nothing when the form is invalid', async () => {
    const c = client()
    const out = await saveStatement(c, 'card', { ...valid, statement_balance: '0' }, null, TODAY)
    expect(out.kind).toBe('invalid')
    expect(c.addStatement).not.toHaveBeenCalled()
  })

  it('adds with one request, or edits the statement being edited', async () => {
    const c = client()
    expect((await saveStatement(c, 'card', valid, null, TODAY)).kind).toBe('saved')
    expect(c.addStatement).toHaveBeenCalledTimes(1)
    expect(c.addStatement).toHaveBeenCalledWith('card', statementBody(valid))
    await saveStatement(c, 'card', valid, 's1', TODAY)
    expect(c.updateStatement).toHaveBeenCalledWith('card', 's1', statementBody(valid))
  })

  it('reports a duplicate date (409) and any other failure', async () => {
    const c = client()
    c.addStatement.mockRejectedValueOnce(httpError(409)).mockRejectedValueOnce(httpError(500)).mockRejectedValueOnce(new Error('offline'))
    expect((await saveStatement(c, 'card', valid, null, TODAY)).kind).toBe('duplicate')
    expect((await saveStatement(c, 'card', valid, null, TODAY)).kind).toBe('error')
    expect((await saveStatement(c, 'card', valid, null, TODAY)).kind).toBe('error')
  })
})

describe('removeStatement (C-9)', () => {
  it('sends nothing when the user keeps it', async () => {
    const c = client()
    const confirm = vi.fn().mockResolvedValue(false)
    expect(await removeStatement(c, confirm, 'card', 's1', { otherStatements: false, currentBalance: '6000.00' })).toBe('cancelled')
    expect(c.deleteStatement).not.toHaveBeenCalled()
  })

  it('names the figure nilu goes back to, then deletes', async () => {
    const c = client()
    const confirm = vi.fn().mockResolvedValue(true)
    expect(await removeStatement(c, confirm, 'card', 's1', { otherStatements: false, currentBalance: '6000.00' })).toBe('deleted')
    expect(confirm).toHaveBeenCalledWith({
      title: 'Delete this statement?',
      body: 'nilu goes back to planning your full current balance of £6,000.00 for this card.',
      confirmLabel: 'Delete statement', cancelLabel: 'Keep it', danger: true,
    })
    expect(c.deleteStatement).toHaveBeenCalledWith('card', 's1')
    await removeStatement(c, confirm, 'card', 's1', { otherStatements: true, currentBalance: '6000.00' })
    expect(confirm.mock.calls[1][0].body).toBe('nilu goes back to your previous statement.')
  })
})

describe('pickStatement (C-11, sec)', () => {
  const mine = { id: 'm1', statement_balance: '5000.00', due_date: '2026-10-31' }

  it('asks first, naming the figures that will be deleted', async () => {
    const c = client()
    const confirm = vi.fn().mockResolvedValue(true)
    expect(await pickStatement(c, confirm, 'card', 'p1', mine, 'Test Bank')).toBe('used')
    expect(confirm).toHaveBeenCalledWith({
      title: 'Use the statement from Test Bank?',
      body: 'Your own figures for this statement (£5,000.00, due 31 Oct 2026) will be deleted.',
      confirmLabel: 'Use this statement', cancelLabel: 'Keep mine', danger: true,
    })
    expect(c.useStatement).toHaveBeenCalledTimes(1)
    expect(c.useStatement).toHaveBeenCalledWith('card', 'p1')
  })

  it('sends nothing when the user keeps theirs, and reports a failure', async () => {
    const c = client()
    expect(await pickStatement(c, vi.fn().mockResolvedValue(false), 'card', 'p1', mine, 'Test Bank')).toBe('cancelled')
    expect(c.useStatement).not.toHaveBeenCalled()
    c.useStatement.mockRejectedValueOnce(httpError(500))
    expect(await pickStatement(c, vi.fn().mockResolvedValue(true), 'card', 'p1', mine, 'Test Bank')).toBe('error')
  })
})

describe('editing helpers', () => {
  const rows = [
    { id: 'm1', account_id: 'c', statement_balance: '5000.00', statement_date: '2026-09-30', due_date: '2026-10-31', minimum_due: '150.00', source: 'manual' as const },
    { id: 'p1', account_id: 'c', statement_balance: '4990.00', statement_date: '2026-09-30', due_date: '2026-10-31', minimum_due: null, source: 'provider' as const },
  ]

  it('fills the edit form from a statement, a missing minimum as blank', () => {
    expect(editFormFor(rows[1])).toEqual({
      form: { statement_balance: '4990.00', statement_date: '2026-09-30', due_date: '2026-10-31', minimum_due: '' },
      replacingProvider: true,
    })
    expect(editFormFor(rows[0]).replacingProvider).toBe(false)
    expect(editFormFor(rows[0]).form.minimum_due).toBe('150.00')
  })

  it('finds the user\'s own statement for a duplicate date, and the one to keep in a pick', () => {
    expect(manualFor(rows, '2026-09-30')?.id).toBe('m1')
    expect(manualFor(rows, '2026-08-31')).toBeUndefined()
  })
})
