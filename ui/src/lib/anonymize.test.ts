import { describe, it, expect } from 'vitest'
import { scramble, type ScrambleCtx } from './anonymize'

// Representative fixtures mirroring every API response that carries money or a
// name. If a new endpoint adds such a field, add it here — a failing assertion
// is the whole point: it stops the field leaking through unscrambled.
const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v))
const K = 2 // doubling makes money assertions trivial to read

function run(fixture: unknown) {
  const reverse = new Map<string, string>()
  const ctx: ScrambleCtx = { k: K, reverse }
  const out = scramble(clone(fixture), ctx)
  return { out: out as any, reverse }
}

describe('anonymize — money', () => {
  it('scales every money field, number or string, by k', () => {
    const { out } = run({
      available_cash: 1000,            // number
      net_worth: '8000',               // decimal string
      credit_owed: 250.5,
      accounts: [{ id: 'a1', current_balance: 2140, available_balance: 2100, overdraft_limit: 500 }],
    })
    expect(out.available_cash).toBe(2000)
    expect(out.net_worth).toBe('16000')
    expect(out.credit_owed).toBe(501)
    expect(out.accounts[0].current_balance).toBe(4280)
    expect(out.accounts[0].available_balance).toBe(4200) // leak-guard: was missing
    expect(out.accounts[0].overdraft_limit).toBe(1000)
    expect(out.accounts[0].id).toBe('a1') // ids never change
  })

  it('treats `total` as money only when a string (aggregate), not a number (count)', () => {
    const list = run({ items: [], total: 60, page: 1, page_size: 50 }).out
    expect(list.total).toBe(60) // pagination count — untouched
    expect(list.page).toBe(1)

    const spend = run({
      total_spent: '1086.42',
      by_category: [{ category: 'Groceries', total: '284.50', count: 12 }],
      top_merchants: [{ merchant: 'Tesco', total: '182.40' }],
    }).out
    expect(spend.total_spent).toBe('2172.84')
    expect(spend.by_category[0].total).toBe('569') // string total = money
    expect(spend.by_category[0].count).toBe(12) // count untouched
    expect(spend.by_category[0].category).toBe('Groceries') // categories stay real
    expect(spend.top_merchants[0].total).toBe('364.8')
  })

  it('scrambles forecast timeline and events', () => {
    const { out } = run({
      min_balance: '610',
      timeline: [{ date: '2026-07-24', balance: 610, events: [{ label: 'Rent', amount: -1100, kind: 'expense' }] }],
    })
    expect(out.min_balance).toBe('1220')
    expect(out.timeline[0].balance).toBe(1220)
    expect(out.timeline[0].events[0].amount).toBe(-2200)
    expect(out.timeline[0].date).toBe('2026-07-24') // dates untouched
    expect(out.timeline[0].events[0].label).not.toBe('Rent') // label pseudonymised
    expect(out.timeline[0].events[0].kind).toBe('expense')
  })

  it('scrambles net-worth history strings', () => {
    const { out } = run([{ date: '2026-07-01', bank: '6000', assets: '2000', net_worth: '8000' }])
    expect(out[0].bank).toBe('12000')
    expect(out[0].assets).toBe('4000')
    expect(out[0].net_worth).toBe('16000')
    expect(out[0].date).toBe('2026-07-01')
  })
})

describe('anonymize — names', () => {
  it('pseudonymises merchant/description/label/name and masks email', () => {
    const { out } = run({
      email: 'real.person@gmail.com',
      items: [{
        id: 't1', merchant_name: 'Tesco', description: 'TESCO *PAYMENT 1023',
        category: 'Groceries', transaction_type: 'debit', amount: 54.2,
        transaction_date: '2026-07-01', is_commitment: true,
      }],
    })
    expect(out.email).not.toContain('real.person')
    expect(out.items[0].merchant_name).not.toBe('Tesco')
    expect(out.items[0].description).not.toBe('TESCO *PAYMENT 1023')
    expect(out.items[0].category).toBe('Groceries') // categories real
    expect(out.items[0].transaction_type).toBe('debit') // enums real
    expect(out.items[0].transaction_date).toBe('2026-07-01')
    expect(out.items[0].is_commitment).toBe(true) // flags real
    expect(out.items[0].id).toBe('t1')
  })

  it('scrambles bank/account names, the drill-down account, and the facet array', () => {
    const { out } = run({
      connections: [{ id: 'b1', provider_name: 'Monzo', is_expired: false }],
      accounts: [{ id: 'a1', display_name: 'Monzo Current', provider_name: 'Monzo' }],
      drill: [{ id: 't1', account: 'Barclays Current', merchant: 'Tesco' }], // spending drill-down row
      merchants: ['Tesco', 'Deliveroo', 'TfL'],
      categories: ['Groceries', 'Transport'],
    })
    expect(out.connections[0].provider_name).not.toBe('Monzo')
    expect(out.accounts[0].display_name).not.toBe('Monzo Current')
    expect(out.drill[0].account).not.toBe('Barclays Current') // leak-guard: was missing
    expect(out.merchants.every((m: string, i: number) => m !== ['Tesco', 'Deliveroo', 'TfL'][i])).toBe(true)
    expect(out.categories).toEqual(['Groceries', 'Transport']) // categories untouched
  })

  it('scrambles commitment match_key and rule pattern (they carry real merchant text)', () => {
    const commitment = run({ id: 'c1', label: 'Netflix', match_key: 'expense:netflix', amount: 15.99 }).out
    expect(commitment.match_key).not.toBe('expense:netflix') // leak-guard: was missing
    const rule = run({ id: 'r1', pattern: 'tesco', category: 'Groceries', enabled: true }).out
    expect(rule.pattern).not.toBe('tesco') // leak-guard: was missing
    expect(rule.category).toBe('Groceries') // categories real
    expect(rule.enabled).toBe(true)
  })

  it('is deterministic and reversible for server-side filtering', () => {
    const a = run({ merchant_name: 'Tesco' })
    const b = run({ items: [{ merchant: 'Tesco' }] })
    // Same real name → same fake everywhere.
    expect(a.out.merchant_name).toBe(b.out.items[0].merchant)
    // The reverse map recovers the real value for outgoing params.
    expect(a.reverse.get(a.out.merchant_name)).toBe('Tesco')
  })
})
