import { describe, it, expect } from 'vitest'
import { consentScopes, cleanDisplayName } from './oauthConsent'

// docs/design/nilu-s08-claude-changes.md (HQ) section 5, K2 and C15.

describe('consentScopes (K2)', () => {
  it('sends read only when neither optional box is ticked', () => {
    expect(consentScopes({ rules: false, planning: false })).toEqual(['finance:read'])
  })

  it('adds planning.write only when its box is ticked', () => {
    expect(consentScopes({ rules: false, planning: true })).toEqual(['finance:read', 'finance:planning.write'])
  })

  it('sends all three when both boxes are ticked', () => {
    expect(consentScopes({ rules: true, planning: true })).toEqual([
      'finance:read',
      'finance:rules.write',
      'finance:planning.write',
    ])
  })
})

describe('cleanDisplayName (C15)', () => {
  it.each([
    ['bidi override', 'Claude\u202eDesktop'],
    ['isolate', 'Claude\u2066Desktop\u2069'],
    ['zero-width space', 'Claude\u200bDesktop'],
    ['zero-width joiner', 'Claude\u200dDesktop'],
    ['BOM', 'Claude\ufeffDesktop'],
    ['control character', 'Claude\u0007Desktop'],
    ['Hangul filler', 'Claude\u3164Desktop'],
    ['combining grapheme joiner', 'Claude\u034fDesktop'],
    ['Khmer inherent vowel', 'Claude\u17b4Desktop'],
  ])('removes a %s', (_label, name) => {
    expect(cleanDisplayName(name)).toBe('ClaudeDesktop')
  })

  it('keeps ordinary names, accents and other scripts', () => {
    expect(cleanDisplayName('Clàude Désktop')).toBe('Clàude Désktop')
    expect(cleanDisplayName('クロード')).toBe('クロード')
  })
})
