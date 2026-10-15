import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import UpcomingLabel from '../components/UpcomingLabel'
import { loanLenders } from './homeOwed'
import { forecastLenders, withLoanLabels } from './loanLabel'
import type { Upcoming } from './upcoming'
import type { Commitment } from '../types'

// P2 (owner 2026-10-15; ux P-10..P-12; sec): a bill linked to a loan reads
// "{lender} loan payment" on Cashflow. Built here from the API's fields.
const linked = (id: string, lender: string, label = 'LOAN DD') => ({ lender, linked_commitment: { id, label } })
const row = (over: Partial<Upcoming> = {}): Upcoming => ({
  key: 'c-1', label: 'LOAN DD', amount: 200, date: '2026-11-01', income: false, commitmentId: 'c1', ...over,
})

describe('withLoanLabels (Coming up)', () => {
  const lenders = loanLenders([linked('c1', 'Lender A'), { lender: 'Unlinked', linked_commitment: null }])

  it('P-11: a lender that already says loan reads "{lender} payment"', () => {
    expect(withLoanLabels([row()], loanLenders([linked('c1', 'Personal loan')]))[0].label).toBe('Personal loan payment')
  })

  it('P-10, P-12: only the linked bill is renamed; amount and date unchanged', () => {
    const [loan, gym] = withLoanLabels([row(), row({ key: 'c-2', label: 'Gym', commitmentId: 'c2' })], lenders)
    expect(loan).toEqual({ ...row(), label: 'Lender A loan payment' })
    expect(gym.label).toBe('Gym')
  })

  it('leaves income and rows without a commitment alone', () => {
    expect(withLoanLabels([row({ income: true })], lenders)[0].label).toBe('LOAN DD')
    expect(withLoanLabels([row({ commitmentId: undefined })], lenders)[0].label).toBe('LOAN DD')
  })

  it('sec: a 100-character lender is kept whole, and markup renders as text', () => {
    const long = 'L'.repeat(100)
    expect(withLoanLabels([row()], loanLenders([linked('c1', long)]))[0].label).toBe(`${long} loan payment`)
    const [item] = withLoanLabels([row()], loanLenders([linked('c1', '<b>x</b>')]))
    const h = renderToStaticMarkup(<MemoryRouter><UpcomingLabel item={item} linkMarker /></MemoryRouter>)
    expect(h).not.toContain('<b>')
    expect(h).toContain('&lt;b&gt;x&lt;/b&gt; loan payment')
  })
})

describe('forecastLenders (forecast events carry only a label)', () => {
  const commitment = (id: string, label: string) => ({ id, label }) as Commitment

  it('maps a linked bill’s label to its lender', () => {
    const map = forecastLenders([linked('c1', 'Lender A', 'LOAN DD')], [commitment('c1', 'LOAN DD'), commitment('c2', 'Gym')])
    expect(map.get('LOAN DD')).toBe('Lender A')
    expect(map.has('Gym')).toBe(false)
  })

  it('never renames when another commitment shares the label', () => {
    const map = forecastLenders([linked('c1', 'Lender A', 'DD')], [commitment('c1', 'DD'), commitment('c2', 'DD')])
    expect(map.size).toBe(0)
  })
})
