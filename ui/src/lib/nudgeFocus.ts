/** The page heading focus falls back to (DashboardPage's h1, tabIndex -1). */
export const PAGE_HEADING_ID = 'cashflow-heading'

/** Where focus goes when nudge `removed` leaves (ux on #302, WCAG 2.4.3): the
 *  next remaining nudge, else the one before it; null: the page heading. */
export function focusTargetAfter(ids: string[], removed: string): string | null {
  const i = ids.indexOf(removed)
  return ids[i + 1] ?? ids[i - 1] ?? null
}
