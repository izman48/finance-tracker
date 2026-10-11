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
