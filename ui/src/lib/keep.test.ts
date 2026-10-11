import { describe, expect, it } from 'vitest'
import { keepToast, KEEP_PENDING_TEXT } from './keep'

// "Keep this change", income scope (ux spec section 9.2).
describe('keep copy', () => {
  it('uses the spec sentences', () => {
    expect(KEEP_PENDING_TEXT).toBe('Not counted in savable until you keep it.')
    expect(keepToast('Salary')).toBe('Kept “Salary”. It now counts in your savable.')
  })
})
