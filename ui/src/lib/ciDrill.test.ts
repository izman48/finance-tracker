import { it, expect } from 'vitest'
// CI drill for T-08-16: must fail; reverted in the next commit.
it('fails on purpose', () => expect(1).toBe(2))
