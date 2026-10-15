import { describe, expect, it } from 'vitest'
import axios from 'axios'
import { bankLinkError } from './bankLink'

// T-12-11: in demo mode Connect/Reconnect are blocked with a toast; the page
// must not also print "Failed to get bank connection URL: …".
describe('bankLinkError', () => {
  it('says nothing for a demo-mode block (the toast already explains)', () => {
    expect(bankLinkError('Failed to get bank connection URL', new axios.Cancel('anonymized-connect-blocked'))).toBe('')
  })
  it('keeps the server detail, else the message, for a real failure', () => {
    expect(bankLinkError('Failed to start reconnecting', { response: { data: { detail: 'No such connection' } } }))
      .toBe('Failed to start reconnecting: No such connection')
    expect(bankLinkError('Failed to get bank connection URL', new Error('Network Error')))
      .toBe('Failed to get bank connection URL: Network Error')
  })
})
