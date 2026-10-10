export const SCOPE_READ = 'finance:read'
export const SCOPE_RULES_WRITE = 'finance:rules.write'
export const SCOPE_PLANNING_WRITE = 'finance:planning.write'

/** The scopes to grant for the boxes ticked on the consent screen. Read is always granted. */
export function consentScopes(ticked: { rules: boolean; planning: boolean }): string[] {
  return [
    SCOPE_READ,
    ...(ticked.rules ? [SCOPE_RULES_WRITE] : []),
    ...(ticked.planning ? [SCOPE_PLANNING_WRITE] : []),
  ]
}

// Controls, format characters (bidi overrides and isolates, zero-width,
// BOM), surrogates, private use, unassigned, line/paragraph separators, and
// letters that render blank. Same set the API refuses at client registration.
const HIDDEN = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\u115f\u1160\u3164\uffa0]|\u034f|\u17b4|\u17b5/gu

/**
 * A third-party-chosen name (an OAuth client's name) with invisible
 * characters removed, so it can't render as another name. Clean before
 * truncating.
 */
export function cleanDisplayName(name: string): string {
  return name.replace(HIDDEN, '')
}
