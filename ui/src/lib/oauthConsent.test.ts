import { describe, it, expect } from 'vitest'
import { consentScopes, cleanDisplayName } from './oauthConsent'

// docs/design/nilu-s08-claude-changes.md (HQ) section 5, K2 and C15.

describe('consentScopes (K2)', () => {
  it('sends read only when no optional box is ticked', () => {
    expect(consentScopes({ rules: false, planning: false, sync: false, budgets: false, rulesEdit: false })).toEqual(['finance:read'])
  })

  it('adds planning.write only when its box is ticked', () => {
    expect(consentScopes({ rules: false, planning: true, sync: false, budgets: false, rulesEdit: false })).toEqual(['finance:read', 'finance:planning.write'])
  })

  it('adds sync only when its box is ticked', () => {
    expect(consentScopes({ rules: false, planning: false, sync: true, budgets: false, rulesEdit: false })).toEqual(['finance:read', 'finance:sync'])
  })

  it('K10: adds budgets.write only when its box is ticked', () => {
    expect(consentScopes({ rules: false, planning: false, sync: false, budgets: true, rulesEdit: false })).toEqual([
      'finance:read',
      'finance:budgets.write',
    ])
  })

  it('K10: planning never implies budgets, nor budgets planning', () => {
    expect(consentScopes({ rules: false, planning: true, sync: false, budgets: false, rulesEdit: false })).not.toContain('finance:budgets.write')
    expect(consentScopes({ rules: false, planning: false, sync: false, budgets: true, rulesEdit: false })).not.toContain('finance:planning.write')
  })

  it('adds rules.edit only when its box is ticked', () => {
    expect(consentScopes({ rules: false, planning: false, sync: false, budgets: false, rulesEdit: true })).toEqual([
      'finance:read',
      'finance:rules.edit',
    ])
  })

  it('adding rule packs never implies editing existing rules, nor the reverse', () => {
    expect(consentScopes({ rules: true, planning: false, sync: false, budgets: false, rulesEdit: false })).not.toContain('finance:rules.edit')
    expect(consentScopes({ rules: false, planning: false, sync: false, budgets: false, rulesEdit: true })).not.toContain('finance:rules.write')
  })

  it('sends all six, each once, when every box is ticked', () => {
    expect(consentScopes({ rules: true, planning: true, sync: true, budgets: true, rulesEdit: true })).toEqual([
      'finance:read',
      'finance:rules.write',
      'finance:planning.write',
      'finance:sync',
      'finance:budgets.write',
      'finance:rules.edit',
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
