import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import AccountSettingsModal from './AccountSettingsModal'
import type { SummaryAccount } from '../types'

// ux on #182: the settings modal is a labelled modal dialog.
const card = {
  id: 'c1', display_name: 'Test Card', provider_name: 'Test Bank', account_type: 'CREDIT_CARD', role: 'credit',
  current_balance: 6000, credit_owed: '6000.00', overdraft_limit: null, repayment_cadence: 'end_of_month',
  repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: 'full_balance',
  repayment_fixed_amount: null, repayment_installments: null, pay_from_account_id: null,
} as SummaryAccount

describe('AccountSettingsModal', () => {
  it('is a modal dialog labelled by its title', () => {
    const h = renderToStaticMarkup(<AccountSettingsModal account={card} spendingAccounts={[]} onClose={() => {}} onSaved={() => {}} />)
    expect(h).toMatch(/role="dialog"[^>]*aria-modal="true"[^>]*aria-labelledby="account-settings-title"/)
    expect(h).toMatch(/<h3 id="account-settings-title"[^>]*>Test Card<\/h3>/)
  })

  // T-10-6b: repayment controls (ux A.5, A.6; existing strategies only).
  const render = (over: Partial<SummaryAccount>) =>
    renderToStaticMarkup(<AccountSettingsModal account={{ ...card, ...over }} spendingAccounts={[]} onClose={() => {}} onSaved={() => {}} />)
  const selected = (h: string, id: string) => h.match(new RegExp(`<select[^>]*id="${id}"[\\s\\S]*?</select>`))![0]
  const chosen = (sel: string) => sel.match(/<option value="([^"]+)" selected="">/)?.[1]

  it('C-13: nothing stored starts on Statement balance and Card due date; a stored full balance is kept', () => {
    const blank = render({ repayment_strategy: null, repayment_cadence: null })
    expect(chosen(selected(blank, 'repayment-strategy'))).toBe('statement_balance')
    expect(chosen(selected(blank, 'repayment-pay-day'))).toBe('card_due_date')
    expect(blank).toContain('Pays what your latest statement says, on its due date. Spending since goes on the next bill.')
    expect(chosen(selected(render({}), 'repayment-strategy'))).toBe('full_balance')
  })

  it('C-16: a standard card on scheduled shows the fix-this notice and keeps Scheduled selected', () => {
    const h = render({ repayment_strategy: 'scheduled', repayment_fix_needed: true })
    expect(h).toContain('This card uses scheduled payments, which are meant for instalment cards like Monzo Flex. Nothing has changed.')
    expect(chosen(selected(h, 'repayment-strategy'))).toBe('scheduled')
    expect(selected(render({}), 'repayment-strategy')).not.toContain('value="scheduled"')
    expect(render({})).not.toContain('This card uses scheduled payments')
  })

  it('the instalment checkbox is labelled, and a day of the month shows the Day input', () => {
    const h = render({ instalment_card: true })
    const box = h.match(/<input[^>]*id="instalment-card"[^>]*>/)![0]
    expect(box).toContain('type="checkbox"')
    expect(box).toContain('checked=""')
    expect(h).toContain('This is an instalment card, like Monzo Flex')
    expect(selected(h, 'repayment-strategy')).toContain('value="scheduled"')
    const monthly = render({ repayment_cadence: 'monthly', repayment_day: 5 })
    expect(chosen(selected(monthly, 'repayment-pay-day'))).toBe('monthly')
    expect(monthly).toMatch(/<label[^>]*for="repayment-day"[^>]*>Day \(1 to 31\)<\/label>/)
  })
})
