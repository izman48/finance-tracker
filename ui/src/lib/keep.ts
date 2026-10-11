/**
 * "Keep this change" (T-08-20; ux spec section 9, income scope). Income
 * Claude raised or confirmed doesn't count in savable until the user keeps
 * it here. Expense changes wait on owner decision D5.
 */

export const KEEP_PENDING_TEXT = 'Not counted in savable until you keep it.'

export const keepToast = (label: string) => `Kept “${label}”. It now counts in your savable.`
