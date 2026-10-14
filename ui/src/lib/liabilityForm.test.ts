import { describe, expect, it, vi } from 'vitest'
import {
  addedToast, blankForm, deleteConfirm, formFor, optOutConfirm, replaceConfirm, saveLiability,
  type LiabilityClient,
} from './liabilityForm'
import type { Asset, Liability } from '../services/api'

// ux T-10-0 B.3-B.5 (add/edit loans and finance). Synthetic fixture.
const loan = (over: Partial<Liability> = {}): Liability => ({
  id: 'l-a', kind: 'loan', lender: 'Test Lender', balance: '9000.00', balance_as_of: '2026-10-01',
  apr: '11.00', payment: '200.00', cadence: 'monthly', start_date: '2026-11-01', end_date: null,
  opted_out: false, current_balance: '9000.00', next_payment_date: '2026-11-01', payments_remaining: 58,
  payoff_date: '2031-08-01', interest_remaining: '2483.22', total_cost: '11483.22', paid_off: false,
  balance_stale: false, linked_commitment: { id: 'c-1', label: 'Test Lender' }, link_result: null, ...over,
})
const filled = () => ({ ...blankForm('2026-10-14'), lender: 'Test Lender', balance: '9000.00', apr: '11', payment: '200.00', start_date: '2026-11-01' })
const ok = (data: Partial<Liability>) => Promise.resolve({ data: loan(data) })
const fail = (status: number, detail: unknown) => Promise.reject({ response: { status, data: { detail } } })
const client = (over: Partial<LiabilityClient> = {}): LiabilityClient => ({
  create: vi.fn(() => ok({ link_result: 'created' })),
  update: vi.fn(() => ok({})),
  remove: vi.fn(() => Promise.resolve({})),
  ...over,
})

describe('saving (B.3)', () => {
  it('L-9: payment blank and not irregular: the payment error shows and nothing is sent', async () => {
    const c = client()
    const out = await saveLiability(c, { ...filled(), payment: '' }, null)
    expect(out).toEqual({ kind: 'invalid', errors: { payment: 'Enter the payment amount, or tick "I repay this loan irregularly".' } })
    expect(c.create).not.toHaveBeenCalled()
  })

  it('L-9: irregular ticked and payment blank: the request is sent without a payment', async () => {
    const c = client()
    await saveLiability(c, { ...filled(), payment: '', opted_out: true }, null)
    expect(c.create).toHaveBeenCalledWith(expect.objectContaining({ opted_out: true, payment: null }))
  })

  it('money and APR go as the strings typed; the whole term set is sent on edit', async () => {
    const c = client()
    await saveLiability(c, filled(), 'l-a')
    expect(c.update).toHaveBeenCalledWith('l-a', {
      kind: 'loan', lender: 'Test Lender', balance: '9000.00', balance_as_of: '2026-10-14', apr: '11',
      payment: '200.00', cadence: 'monthly', start_date: '2026-11-01', end_date: null, opted_out: false,
    })
  })

  it('only format is checked in the browser: a number, a date, the required fields', async () => {
    const out = await saveLiability(client(), { ...filled(), lender: '', balance: '9,000', start_date: '' }, null)
    expect(out.kind).toBe('invalid')
    expect(Object.keys((out as { errors: object }).errors).sort()).toEqual(['balance', 'lender', 'start_date'])
  })

  it('L-10: a created bill gives the "now in your bills" toast', async () => {
    const out = await saveLiability(client(), filled(), null)
    expect(out.kind).toBe('saved')
    expect(addedToast((out as { liability: Liability }).liability)).toBe('Loan added. £200.00 a month is now in your bills.')
  })

  it('a linked existing bill, or none, have their own toasts', () => {
    expect(addedToast(loan({ link_result: 'linked', linked_commitment: { id: 'c', label: 'LOAN DD' } })))
      .toBe('Loan added. Linked to your existing bill "LOAN DD".')
    expect(addedToast(loan({ link_result: null, opted_out: true, linked_commitment: null })))
      .toBe('Loan added. No repeating payment was added.')
  })

  it('L-11: a 409 choose_commitment returns the candidates; the choice is sent with the next request', async () => {
    const candidates = [{ id: 'c1', label: 'LOAN DD', amount: '200.00', cadence: 'monthly', interval_days: null, next_date: '2026-11-28' }]
    const c = client({ create: vi.fn().mockReturnValueOnce(fail(409, { code: 'choose_commitment', candidates })).mockReturnValueOnce(ok({ link_result: 'linked' })) })
    const first = await saveLiability(c, filled(), null)
    expect(first).toEqual({ kind: 'choose', candidates })
    await saveLiability(c, filled(), null, { commitmentChoice: 'c1' })
    expect(c.create).toHaveBeenLastCalledWith(expect.objectContaining({ commitment_choice: 'c1' }))
  })

  it('L-12: a 422 naming a field goes under it; the payment-too-low message goes on top', async () => {
    const named = client({ create: vi.fn(() => fail(422, [{ loc: ['body', 'apr'], msg: 'x' }])) })
    expect(await saveLiability(named, filled(), null)).toEqual({ kind: 'invalid', errors: { apr: 'Enter a number from 0 to 100. Use the APR on your lender\'s statement.' } })
    const tooLow = client({ create: vi.fn(() => fail(422, "A payment of £78.61 doesn't cover the interest of £78.61 it would be charged. Increase the payment.")) })
    expect(await saveLiability(tooLow, filled(), null)).toEqual({ kind: 'message', message: "A payment of £78.61 doesn't cover the interest of £78.61 it would be charged. Increase the payment." })
  })

  it('a 422 with no field (a cross-field rule) goes under the field it is about', async () => {
    const cases: [string, string][] = [
      ["Value error, The balance date can't be in the future", 'balance_as_of'],
      ['Value error, The start date must be within a year from today', 'start_date'],
      ['Value error, The final payment must be after the start date', 'end_date'],
    ]
    for (const [msg, field] of cases) {
      const c = client({ create: vi.fn(() => fail(422, [{ loc: [], msg }])) })
      const out = await saveLiability(c, filled(), null)
      expect(out).toEqual({ kind: 'invalid', errors: { [field]: msg.replace('Value error, ', '') + '.' } })
    }
  })

  it('an unknown no-field 422 shows the server message, never "fields marked below"', async () => {
    const c = client({ create: vi.fn(() => fail(422, [{ loc: [], msg: 'Value error, Something else is wrong' }])) })
    expect(await saveLiability(c, filled(), null)).toEqual({ kind: 'message', message: 'Something else is wrong' })
  })

  it('L-16: a 404 says the loan is gone', async () => {
    const gone = client({ update: vi.fn(() => fail(404, 'Liability not found')) })
    expect(await saveLiability(gone, filled(), 'l-x')).toEqual({ kind: 'not_found' })
  })

  it('5xx or offline: nothing changed', async () => {
    const down = client({ create: vi.fn(() => Promise.reject(new Error('offline'))) })
    expect(await saveLiability(down, filled(), null)).toEqual({ kind: 'error' })
  })

  it('L-15: replacing an asset sends the picked id, never the name', async () => {
    const c = client()
    await saveLiability(c, { ...filled(), replaces_asset_id: 'asset-7' }, null)
    expect(c.create).toHaveBeenCalledWith(expect.objectContaining({ replaces_asset_id: 'asset-7' }))
    expect(JSON.stringify((c.create as ReturnType<typeof vi.fn>).mock.calls[0][0])).not.toContain('Car loan')
  })

  it('formFor fills the edit form from the stored terms', () => {
    expect(formFor(loan({ end_date: '2031-01-01' }))).toMatchObject({ lender: 'Test Lender', balance: '9000.00', apr: '11.00', end_date: '2031-01-01', opted_out: false })
  })
})

describe('confirmations (B.5)', () => {
  it('L-14: deleting a linked loan says the payment stays as a bill', () => {
    expect(deleteConfirm(loan())).toEqual({
      title: 'Delete "Test Lender"?',
      body: 'This loan stops counting as £9,000 of debt in your net worth. The £200.00 monthly payment stays in your bills as a normal bill, so it still comes out of your forecast.',
      confirmLabel: 'Delete loan', cancelLabel: 'Keep it', danger: true,
    })
  })

  it('deleting an unlinked loan says only the net worth part', () => {
    expect(deleteConfirm(loan({ linked_commitment: null })).body).toBe('This loan stops counting as £9,000 of debt in your net worth.')
  })

  it('L-13: opting out of a linked loan names its payment', () => {
    expect(optOutConfirm(loan())).toEqual({
      title: 'Stop the repeating payment?',
      body: 'The £200.00 monthly bill for "Test Lender" is removed, so it no longer comes out of your forecast or safe-to-spend. The balance stays at £9,000 as entered.',
      confirmLabel: 'Remove the bill', cancelLabel: 'Keep the bill', danger: true,
    })
  })

  it('L-15: replacing an asset names it and its value', () => {
    const asset = { id: 'asset-7', name: 'Car loan', asset_type: 'loan', valuations: [{ id: 'v', value: '-9000', valued_at: '2026-09-01' }] } as Asset
    expect(replaceConfirm(asset)).toEqual({
      title: 'Replace "Car loan" with this loan?',
      body: 'The balance sheet entry "Car loan" (−£9,000) is removed and this loan counts instead, so your debt is counted once.',
      confirmLabel: 'Replace it', cancelLabel: 'Cancel',
    })
  })
})
