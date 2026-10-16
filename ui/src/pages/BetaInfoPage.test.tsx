import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { PrivacyPage, PSU_IP_NOTICE } from './BetaInfoPage'

// ux spec section 10, PV1 (T-08-22): refreshing in the app sends the user's
// network address to TrueLayer (X-PSU-IP), so the notice says so.
describe('PrivacyPage', () => {
  it('PV1: says the network address goes to TrueLayer on a refresh, after the TrueLayer paragraph', () => {
    expect(PSU_IP_NOTICE).toBe(
      "When you refresh your banks in nilu, we share your device's network address with TrueLayer, our bank-data provider, so your bank knows you asked.",
    )
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PrivacyPage />
      </MemoryRouter>,
    ).replace(/&#x27;/g, "'")
    const section = html.slice(html.indexOf('Why and who receives it'), html.indexOf('Your control'))
    expect(section).toContain(`<p>${PSU_IP_NOTICE}</p>`)
    expect(section.indexOf('TrueLayer and the email provider')).toBeLessThan(section.indexOf(PSU_IP_NOTICE))
  })
})

// T-12-13 (sec): every unencrypted field group is listed, in the API's exact
// words (api/app/core/privacy_plaintext.py; .github/scripts/check_privacy_copy.py
// fails CI if a phrase goes missing), and deleted planned items are said to
// be kept, encrypted, until purge.
describe('PrivacyPage unencrypted fields', () => {
  it('lists every group as an item, and says what happens to deleted planned items', async () => {
    const { UNENCRYPTED_FIELDS, DELETED_PLANNED_NOTE } = await import('../copy/privacy')
    const html = renderToStaticMarkup(<MemoryRouter><PrivacyPage /></MemoryRouter>).replace(/&#x27;/g, "'")
    expect(UNENCRYPTED_FIELDS.length).toBe(10)
    for (const phrase of UNENCRYPTED_FIELDS) expect(html).toContain(`<li>${phrase}</li>`)
    expect(html).toContain(DELETED_PLANNED_NOTE)
    expect(html).not.toContain('transaction dates, categories and account types.')
  })
})

// sec-1 on #252: a Claude connection also unlocks the key while active, and
// Claude (Anthropic) receives what the user asks it about.
describe('PrivacyPage and Claude connections', () => {
  it('says a Claude connection unlocks the key while active, how to end it, and that Claude receives what you ask about', () => {
    const t = renderToStaticMarkup(<MemoryRouter><PrivacyPage /></MemoryRouter>).replace(/&#x27;/g, "'").replace(/<[^>]+>/g, ' ')
    expect(t).toContain('a Claude connection you approve while it is active')
    expect(t).toContain('Revoking the connection ends that.')
    expect(t).toContain('Once you connect Claude (Anthropic), it receives the data you ask it about.')
    expect(t).toContain("a Claude connection's token (we keep only a hash of that token)")
  })
})
