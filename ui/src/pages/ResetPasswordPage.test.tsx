import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import ResetPasswordPage from './ResetPasswordPage'

// T-12-13: the recovery-code help names everything a reset without the code
// deletes (services/key_loss_purge.py), budgets and holdings included.
describe('ResetPasswordPage', () => {
  it('the recovery-code help lists budgets, holdings and debts', () => {
    const t = renderToStaticMarkup(<MemoryRouter initialEntries={['/reset-password?token=t']}><ResetPasswordPage /></MemoryRouter>)
      .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
    expect(t).toContain('bank data, commitments, planned events, budgets, rules, holdings, debts and the history of changes made by Claude')
  })
})
