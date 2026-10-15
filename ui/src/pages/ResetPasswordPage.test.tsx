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
    // ux on #254: the help line meets 4.5:1 contrast.
    const h = renderToStaticMarkup(<MemoryRouter initialEntries={['/reset-password?token=t']}><ResetPasswordPage /></MemoryRouter>)
    expect(h).toMatch(/<p class="text-xs text-slate-400 mt-1.5">\s*The code you saved at signup/)
  })
})
