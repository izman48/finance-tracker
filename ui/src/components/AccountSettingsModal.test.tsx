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
})
