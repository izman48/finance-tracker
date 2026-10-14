import { describe, expect, it } from 'vitest'
import { EXPLAIN } from './statExplainers'

// T-10-12 (H3): these must match what the API computes today. Net worth
// subtracts liabilities (T-10-7b), and cards are repaid by the strategies
// the settings offer (T-10-6b).
describe('EXPLAIN', () => {
  it('net worth says loans and finance are subtracted', () => {
    expect(EXPLAIN.netWorth).toBe(
      'Your cash, savings and the assets you’ve added, minus what you owe. What you owe is your credit cards plus your loans and finance.',
    )
  })

  it('credit owed names today’s repayment options', () => {
    expect(EXPLAIN.creditOwed).toBe(
      'What you owe across your credit cards. Each card is repaid the way its settings say: the statement balance, the full balance, a fixed amount or instalments. A card with no repayment set up isn’t in your forecast.',
    )
  })
})
