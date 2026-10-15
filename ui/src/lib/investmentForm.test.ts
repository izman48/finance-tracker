import { describe, expect, it } from 'vitest'
import {
  blankInvestment, checkInvestment, commitmentLabel, deleteLinkedConfirm, investmentFor, nextDateForDay,
  saveInvestment, stopBillConfirm, type InvestmentClient, type InvestmentFormState,
} from './investmentForm'
import type { Asset } from '../services/api'

// Add and edit an investment (T-11-5d; ux T-11-2 flow 1, I-6..I-13). Pure:
// the requests a save sends are checked against a fake client. Synthetic figures.
const TODAY = '2026-10-15'

function fakeClient(over: Partial<Record<keyof InvestmentClient, (...a: any[]) => Promise<any>>> = {}) {
  const calls: [string, ...unknown[]][] = []
  const rec = (name: keyof InvestmentClient, impl?: (...a: any[]) => Promise<any>) => async (...args: unknown[]) => {
    calls.push([name, ...args])
    return impl ? impl(...args) : { data: { id: 'new-1' } }
  }
  const client: InvestmentClient = {
    create: rec('create', over.create),
    update: rec('update', over.update),
    addValuation: rec('addValuation', over.addValuation),
    setContribution: rec('setContribution', over.setContribution),
    stopContribution: rec('stopContribution', over.stopContribution),
  }
  return { client, calls }
}

const filled = (over: Partial<InvestmentFormState> = {}): InvestmentFormState => ({
  ...blankInvestment(TODAY, 'acc-1'), name: 'Test ISA', asset_type: 'isa', value: '0', growth: '7', contribution: '1000', ...over,
})
const http = (status: number, detail: unknown) => Object.assign(new Error('http'), { response: { status, data: { detail } } })

describe('the form fields', () => {
  it('defaults: ISA, the first current account, the day of the month today (capped at 28)', () => {
    expect(blankInvestment('2026-10-15', 'acc-1')).toMatchObject({ asset_type: 'isa', pay_from: 'acc-1', day: '15', commit: false })
    expect(blankInvestment('2026-10-30', null)).toMatchObject({ pay_from: '', day: '28' })
  })
  it('I-6: the checkbox label follows the amount; disabled with no amount above 0', () => {
    expect(commitmentLabel('1000')).toEqual({ text: 'Add £1,000 a month as a commitment', enabled: true })
    expect(commitmentLabel('250.50')).toEqual({ text: 'Add £250.50 a month as a commitment', enabled: true })
    for (const none of ['', '0', 'abc']) expect(commitmentLabel(none)).toEqual({ text: 'Add a monthly contribution as a commitment', enabled: false })
  })
  it('the next payment is the chosen day this month, or next month once it has passed', () => {
    expect(nextDateForDay('20', '2026-10-15')).toBe('2026-10-20')
    expect(nextDateForDay('15', '2026-10-15')).toBe('2026-10-15')
    expect(nextDateForDay('3', '2026-10-15')).toBe('2026-11-03')
    expect(nextDateForDay('3', '2026-12-15')).toBe('2027-01-03')
  })
  it('editing a linked holding shows the bill: ticked, its amount, pay-from and day (I-10)', () => {
    const asset: Asset = {
      id: 'a1', name: 'Test ISA', asset_type: 'isa', assumed_growth_pct: '7.00', monthly_contribution: null,
      valuations: [{ id: 'v', value: '18000.00', valued_at: '2026-10-01' }],
      linked_commitment: { id: 'c1', label: 'Test ISA contribution', amount: '1000.00', next_date: '2026-10-28', pay_from_account_id: 'acc-2' },
    }
    expect(investmentFor(asset, 'acc-1')).toMatchObject({
      name: 'Test ISA', value: '18000.00', growth: '7.00', contribution: '1000.00', commit: true, pay_from: 'acc-2', day: '28',
    })
  })
})

describe('validation: shown under the field, nothing sent', () => {
  it.each([
    [{ name: ' ' }, 'name', 'Give it a name.'],
    [{ value: '-1' }, 'value', 'Enter the value today, 0 or more.'],
    [{ value: '' }, 'value', 'Enter the value today, 0 or more.'],
    [{ growth: '60' }, 'growth', 'Growth must be between −100% and 50% a year.'],
    [{ growth: '-100.5' }, 'growth', 'Growth must be between −100% and 50% a year.'],
    [{ contribution: '-5' }, 'contribution', 'Enter 0 or more.'],
    [{ contribution: '10000000.01' }, 'contribution', 'Enter 0 or more.'],
    [{ commit: true, pay_from: '' }, 'pay_from', 'Choose an account to pay from.'],
  ])('%o -> %s', async (over, field, message) => {
    expect(checkInvestment(filled(over as Partial<InvestmentFormState>), true)[field as 'name']).toBe(message)
    const { client, calls } = fakeClient()
    const out = await saveInvestment(client, filled(over as Partial<InvestmentFormState>), { asset: null, today: TODAY, hasCurrentAccount: true })
    expect(out.kind).toBe('invalid')
    expect(calls).toEqual([])
  })
  it('no current account to pay from', () => {
    expect(checkInvestment(filled({ commit: true, pay_from: '' }), false).pay_from).toBe('Connect a bank first, or leave this off.')
  })
  it('blank growth is allowed (growth not set)', () => {
    expect(checkInvestment(filled({ growth: '' }), true)).toEqual({})
  })
})

describe('add', () => {
  it('without a commitment: one create with the contribution on the holding', async () => {
    const { client, calls } = fakeClient()
    const out = await saveInvestment(client, filled(), { asset: null, today: TODAY, hasCurrentAccount: true })
    expect(out).toEqual({ kind: 'saved', assetId: 'new-1' })
    expect(calls).toEqual([['create', {
      name: 'Test ISA', asset_type: 'isa', value: 0, assumed_growth_pct: 7, monthly_contribution: 1000,
    }]])
  })

  it('I-7: with the box ticked and no candidates, create then link a new bill', async () => {
    const { client, calls } = fakeClient()
    const out = await saveInvestment(client, filled({ commit: true, day: '28' }), { asset: null, today: TODAY, hasCurrentAccount: true })
    expect(out).toEqual({ kind: 'saved', assetId: 'new-1' })
    expect(calls).toEqual([
      ['create', { name: 'Test ISA', asset_type: 'isa', value: 0, assumed_growth_pct: 7, monthly_contribution: null }],
      ['setContribution', 'new-1', { amount: '1000.00', next_date: '2026-10-28', pay_from_account_id: 'acc-1' }],
    ])
  })

  it('I-8: candidates make the user choose; nothing is taken over before a choice', async () => {
    const candidates = [{ id: 'c9', label: 'ISA DD', amount: '1000.00', cadence: 'monthly', interval_days: null, next_date: '2026-10-28' }]
    const { client, calls } = fakeClient({
      setContribution: async () => { throw http(409, { code: 'choose_commitment', candidates }) },
    })
    const out = await saveInvestment(client, filled({ commit: true }), { asset: null, today: TODAY, hasCurrentAccount: true })
    expect(out).toEqual({ kind: 'choose', assetId: 'new-1', candidates })
    expect(calls.filter(([n]) => n === 'setContribution')).toHaveLength(1)
    expect((calls[1][2] as Record<string, unknown>).commitment_choice).toBeUndefined()
  })

  it('I-9: the choice links that bill, without creating the holding again', async () => {
    const { client, calls } = fakeClient()
    const out = await saveInvestment(client, filled({ commit: true, day: '28' }),
      { asset: null, today: TODAY, hasCurrentAccount: true, createdId: 'new-1', commitmentChoice: 'c9' })
    expect(out).toEqual({ kind: 'saved', assetId: 'new-1' })
    expect(calls).toEqual([['setContribution', 'new-1', {
      amount: '1000.00', next_date: '2026-10-28', pay_from_account_id: 'acc-1', commitment_choice: 'c9',
    }]])
  })

  it('I-13: a server error says nothing changed', async () => {
    const { client } = fakeClient({ create: async () => { throw http(500, 'boom') } })
    expect(await saveInvestment(client, filled(), { asset: null, today: TODAY, hasCurrentAccount: true })).toEqual({ kind: 'error' })
  })
})

describe('edit', () => {
  const unlinked: Asset = {
    id: 'a1', name: 'Test ISA', asset_type: 'isa', assumed_growth_pct: '7.00', monthly_contribution: '500.00',
    valuations: [{ id: 'v', value: '18000.00', valued_at: '2026-10-01' }], linked_commitment: null,
  }
  const linked: Asset = {
    ...unlinked, monthly_contribution: null,
    linked_commitment: { id: 'c1', label: 'Test ISA contribution', amount: '1000.00', next_date: '2026-10-28', pay_from_account_id: 'acc-1' },
  }

  it('only changed fields are sent; an unchanged value sends no valuation', async () => {
    const { client, calls } = fakeClient()
    await saveInvestment(client, { ...investmentFor(unlinked, 'acc-1'), growth: '6' }, { asset: unlinked, today: TODAY, hasCurrentAccount: true })
    expect(calls).toEqual([['update', 'a1', { assumed_growth_pct: 6 }]])
  })

  it('a new value today is a valuation; nothing else unchanged is sent', async () => {
    const { client, calls } = fakeClient()
    await saveInvestment(client, { ...investmentFor(unlinked, 'acc-1'), value: '19000' }, { asset: unlinked, today: TODAY, hasCurrentAccount: true })
    expect(calls).toEqual([['addValuation', 'a1', { value: 19000 }]])
  })

  it('a linked holding never sends the legacy contribution; a new amount updates the bill', async () => {
    const { client, calls } = fakeClient()
    await saveInvestment(client, { ...investmentFor(linked, 'acc-1'), contribution: '1200' }, { asset: linked, today: TODAY, hasCurrentAccount: true })
    expect(calls).toEqual([['setContribution', 'a1', { amount: '1200.00', next_date: '2026-10-28', pay_from_account_id: 'acc-1' }]])
  })

  it('I-10: unticking a linked holding stops the bill (after the confirm, in the component)', async () => {
    const { client, calls } = fakeClient()
    await saveInvestment(client, { ...investmentFor(linked, 'acc-1'), commit: false }, { asset: linked, today: TODAY, hasCurrentAccount: true })
    expect(calls).toEqual([['stopContribution', 'a1']])
  })

  it('ticking on an unlinked holding links it (the legacy figure is not patched)', async () => {
    const { client, calls } = fakeClient()
    await saveInvestment(client, { ...investmentFor(unlinked, 'acc-1'), commit: true, day: '28' }, { asset: unlinked, today: TODAY, hasCurrentAccount: true })
    expect(calls).toEqual([['setContribution', 'a1', { amount: '500.00', next_date: '2026-10-28', pay_from_account_id: 'acc-1' }]])
  })

  it('nothing changed: nothing sent', async () => {
    const { client, calls } = fakeClient()
    const out = await saveInvestment(client, investmentFor(linked, 'acc-1'), { asset: linked, today: TODAY, hasCurrentAccount: true })
    expect(out).toEqual({ kind: 'saved', assetId: 'a1' })
    expect(calls).toEqual([])
  })
})

describe('confirm copy', () => {
  const linked = { name: 'Meridian S&S ISA', linked_commitment: { id: 'c1', label: 'Meridian S&S ISA contribution' } } as Asset
  it('deleting a linked holding says the bill stays (I-11)', () => {
    expect(deleteLinkedConfirm(linked)).toEqual({
      title: 'Delete Meridian S&S ISA?',
      body: 'The bill "Meridian S&S ISA contribution" stays as a normal bill. You can delete it in Commitments.',
      confirmLabel: 'Delete', cancelLabel: 'Cancel', danger: true,
    })
  })
  it('unticking a bill nilu added says it is removed and the contribution stays (I-10)', () => {
    expect(stopBillConfirm({ ...linked, linked_commitment: { ...linked.linked_commitment!, created: true } })).toEqual({
      title: 'Stop counting this as a bill?',
      body: '"Meridian S&S ISA contribution" will be removed from your bills. The monthly contribution stays on the investment.',
      confirmLabel: 'Remove bill', cancelLabel: 'Cancel', danger: true,
    })
  })
  it('unticking a bill the user already had says it stays as a normal bill (lead, #221)', () => {
    expect(stopBillConfirm({ ...linked, linked_commitment: { ...linked.linked_commitment!, created: false } })).toEqual({
      title: 'Stop counting this as a bill?',
      body: '"Meridian S&S ISA contribution" stays in your bills as a normal bill, no longer linked to this investment. The monthly contribution stays on the investment.',
      confirmLabel: 'Unlink bill', cancelLabel: 'Cancel', danger: false,
    })
  })
})
