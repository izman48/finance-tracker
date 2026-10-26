/**
 * Plain-words copy for the "Changes made by Claude" screen (T-08-5; ux spec
 * nilu-s08-claude-changes.md section 1). Pure functions, so every sentence
 * the screen can show is unit-tested.
 *
 * Labels, names and client names come from bank feeds, from Claude and from
 * whoever registered the OAuth client. They are returned as plain strings and
 * rendered as text only.
 */
import axios from 'axios'
import { cadenceLabel } from './cadence'
import { dateDayMonth, gbp, gbp0 } from './format'
import { cleanDisplayName } from './oauthConsent'

export type AuditValue = string | number | boolean | null

export interface AuditChange {
  field: string
  before: AuditValue
  after: AuditValue
}

export interface AuditItem {
  id: string
  created_at: string
  tool: string
  batch_id: string | null
  client_name: string | null
  connection_created_at: string | null
  target_kind: 'planned_event' | 'commitment' | 'budget' | 'rule' | string
  target_id: string
  target_label: string
  changes: AuditChange[]
  undone_at: string | null
  // Income Claude raised or confirmed: waiting for the user to keep it (T-08-20).
  keep?: 'pending' | 'kept' | null
  keep_kind?: 'income' | 'expense_cut' | null
  kept_at?: string | null
}

export interface AuditPage {
  items: AuditItem[]
  next_cursor: string | null
}

/** One line under the title; `before` is absent for adds and removes. */
export interface ChangeLine {
  label: string
  before?: string
  after: string
}

const quoted = (s: string) => `“${s}”`

const changeOf = (item: AuditItem, field: string) => item.changes.find((c) => c.field === field)

const isConfirmation = (item: AuditItem) => {
  const status = changeOf(item, 'status')
  return item.tool === 'update_commitment' && status?.before === 'suggested' && status.after === 'confirmed'
}

const isIncome = (item: AuditItem) => changeOf(item, 'direction')?.after === 'income'

/** set_budgets made the budget (its limit had no "before"), rather than changing it. */
const isBudgetCreate = (item: AuditItem) =>
  item.tool === 'set_budgets' && changeOf(item, 'limit_pounds')?.before === null

/** update_rule switched the rule off (enabled true -> false), rather than editing it. */
const isSwitchOff = (item: AuditItem) => changeOf(item, 'enabled')?.after === false

export function changeTitle(item: AuditItem): string {
  const name = quoted(item.target_label)
  switch (item.tool) {
    case 'add_planned_event':
      return isIncome(item) ? `Added expected income: ${name}` : `Added a planned expense: ${name}`
    case 'remove_planned_event':
      return `Removed a planned event: ${name}`
    case 'dismiss_commitment':
      return `Dismissed the commitment ${name}`
    case 'update_commitment':
      return isConfirmation(item) ? `Confirmed ${name} as a commitment` : `Changed the commitment ${name}`
    case 'set_budgets':
      return isBudgetCreate(item) ? `Set a budget: ${name}` : `Changed the budget ${name}`
    case 'pause_budget':
      return `Paused the budget ${name}`
    case 'resume_budget':
      return `Resumed the budget ${name}`
    case 'remove_budget':
      return `Removed the budget ${name}`
    case 'update_rule':
      return isSwitchOff(item) ? `Switched off the rule ${name}` : `Changed the rule ${name}`
    default:
      return `Changed ${name}`
  }
}

const FIELD_LABEL: Record<string, string> = {
  label: 'Name',
  name: 'Name',
  amount: 'Amount',
  cadence: 'How often',
  next_date: 'Next date',
  start_date: 'Date',
  card_account_id: 'Card',
  status: 'Status',
}

const STATUS_LABEL: Record<string, string> = {
  suggested: 'Suggested',
  confirmed: 'Confirmed',
  dismissed: 'Dismissed',
}

function formatValue(
  field: string,
  value: AuditValue,
  accountNames: Record<string, string>,
  tool: string,
): string {
  if (field === 'card_account_id') {
    if (value === null) return 'None'
    return accountNames[String(value)] ?? 'A card'
  }
  if (value === null) return '—'
  switch (field) {
    case 'amount':
      return gbp(Number(value))
    case 'next_date':
    case 'start_date':
      return dateDayMonth(String(value))
    case 'cadence':
      return cadenceLabel({ cadence: String(value) })
    case 'status':
      // A dismissal takes away something the user had: "Active", not "Confirmed".
      if (tool === 'dismiss_commitment' && value === 'confirmed') return 'Active'
      return STATUS_LABEL[String(value)] ?? String(value)
    default:
      return String(value)
  }
}

const LIMIT_LABEL = 'Limit for this pay cycle'
const budgetStatus = (paused: boolean, active: boolean) => (!active ? 'Removed' : paused ? 'Paused' : 'Active')

/** A budget row's lines (concept 6): the limit, and the status in plain words. */
function budgetLines(item: AuditItem): ChangeLine[] {
  const limit = changeOf(item, 'limit_pounds')
  if (isBudgetCreate(item)) return [{ label: LIMIT_LABEL, after: gbp0(Number(limit?.after)) }]
  const lines: ChangeLine[] = []
  if (limit) lines.push({ label: LIMIT_LABEL, before: gbp0(Number(limit.before)), after: gbp0(Number(limit.after)) })
  const paused = changeOf(item, 'paused')
  const active = changeOf(item, 'active')
  if (paused || active) {
    // A field that didn't change isn't in the audit row: a pause was of an active budget, a removal of an unpaused one.
    const before = budgetStatus(Boolean(paused?.before ?? false), Boolean(active?.before ?? true))
    const after = budgetStatus(Boolean(paused?.after ?? false), Boolean(active?.after ?? true))
    lines.push({ label: 'Status', before, after })
  }
  return lines
}

const RULE_FIELD_LABEL: Record<string, string> = {
  pattern: 'Matches',
  match_type: 'How it matches',
  match_field: 'Looks at',
  category: 'Category',
  counts_as: 'Counts as',
  enabled: 'Status',
}

const RULE_VALUE_LABEL: Record<string, Record<string, string>> = {
  match_type: { exact: 'Exact text', contains: 'Contains', regex: 'Pattern (regex)' },
  match_field: { any: 'Merchant or description', merchant: 'Merchant', description: 'Description' },
  counts_as: { spending: 'Spending', transfer: 'Transfer', card_payment: 'Card repayment' },
}

function ruleValue(field: string, value: AuditValue): string {
  if (field === 'enabled') return value === false ? 'Off' : 'On'
  if (field === 'counts_as' && value === null) return 'Automatic'
  return RULE_VALUE_LABEL[field]?.[String(value)] ?? String(value)
}

/** A rule row's lines: each matching field that changed, in plain words. */
function ruleLines(item: AuditItem): ChangeLine[] {
  return item.changes
    .filter((c) => c.field in RULE_FIELD_LABEL)
    .map((c) => ({ label: RULE_FIELD_LABEL[c.field], before: ruleValue(c.field, c.before), after: ruleValue(c.field, c.after) }))
}

/** The lines under a row's title (1.4). Fields without a plain-words name are left out. */
export function changeLines(item: AuditItem, accountNames: Record<string, string>): ChangeLine[] {
  const fmt = (field: string, v: AuditValue) => formatValue(field, v, accountNames, item.tool)

  if (item.target_kind === 'budget') return budgetLines(item)
  if (item.target_kind === 'rule') return ruleLines(item)

  if (item.tool === 'add_planned_event' || item.tool === 'remove_planned_event') {
    // Adds and removes have no before/after: one value per line (a remove's
    // audit records amount and date unchanged, next to active true -> false).
    const lines: ChangeLine[] = []
    for (const field of ['amount', 'start_date']) {
      const c = changeOf(item, field)
      if (c) lines.push({ label: FIELD_LABEL[field], after: fmt(field, c.after) })
    }
    if (item.tool === 'add_planned_event' && isIncome(item)) {
      lines.push({ label: 'Counted in safe to spend', after: 'No, not until it arrives' })
    }
    return lines
  }

  return item.changes
    .filter((c) => c.field in FIELD_LABEL)
    .map((c) => ({ label: FIELD_LABEL[c.field], before: fmt(c.field, c.before), after: fmt(c.field, c.after) }))
}

const CLIENT_NAME_MAX = 40

/** "via {name}" as plain text: hidden characters removed first, then cut at 40. */
export function clientText(name: string | null): { text: string; title: string | undefined } {
  const clean = cleanDisplayName(name ?? '').trim()
  if (!clean) return { text: 'via an unnamed app', title: undefined }
  const shown = clean.length > CLIENT_NAME_MAX ? `${clean.slice(0, CLIENT_NAME_MAX)}…` : clean
  return { text: `via ${shown}`, title: clean }
}

/** "12 Oct, 14:32" in local time; the year is added when it isn't this year. */
export function metaTime(iso: string, now: Date = new Date()): string {
  const d = new Date(iso)
  const day = d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
  })
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${day}, ${time}`
}

/** Consecutive rows that share a batch id (one change in several steps, e.g. a merge). */
export function groupBatches(items: AuditItem[]): { batch: boolean; items: AuditItem[] }[] {
  const groups: { batch: boolean; items: AuditItem[] }[] = []
  for (const it of items) {
    const last = groups[groups.length - 1]
    if (it.batch_id && last && last.items[0].batch_id === it.batch_id) {
      last.items.push(it)
      last.batch = true
    } else {
      groups.push({ batch: false, items: [it] })
    }
  }
  return groups
}

/** The toast after a successful undo (1.5). */
export function undoToast(item: AuditItem): string {
  const name = quoted(item.target_label)
  switch (item.tool) {
    case 'add_planned_event':
      return `Removed ${name} from your planned events.`
    case 'remove_planned_event':
      return `Put ${name} back in your planned events.`
    case 'dismiss_commitment':
      return `${name} is back in your commitments.`
    case 'set_budgets':
      return isBudgetCreate(item) ? `Removed the budget ${name}.` : `Put the budget ${name} back to how it was.`
    case 'pause_budget':
      return `Resumed the budget ${name}.`
    case 'resume_budget':
      return `Paused the budget ${name} again.`
    case 'remove_budget':
      return `Put the budget ${name} back.`
    case 'update_rule':
      return isSwitchOff(item) ? `Switched the rule ${name} back on.` : `Put the rule ${name} back to how it was.`
    default:
      return `Put ${name} back to how it was.`
  }
}

/**
 * 'changed': 409, the item moved on since. 'rate': 429. 'other': the server
 * answered with an error, so nothing was undone. 'unknown': no answer (timeout
 * or network error), so the undo may or may not have gone through.
 */
export type UndoFailure = 'changed' | 'rate' | 'other' | 'unknown'

/** The row state for a failed undo, from the HTTP status only (never the server's text). */
export function undoFailure(status: number | undefined): UndoFailure {
  if (status === undefined) return 'unknown'
  if (status === 409) return 'changed'
  if (status === 429) return 'rate'
  return 'other'
}

/**
 * The row state for whatever an undo request threw. null for a write the API
 * client blocked while anonymised: it shows its own toast, so the row stays as it was.
 */
export function failureFromError(err: unknown): UndoFailure | null {
  if (axios.isCancel(err)) return null
  return undoFailure((err as { response?: { status?: number } } | null)?.response?.status)
}

/** After an undo the first page is refetched: its rows replace ours, older loaded rows stay. */
export function mergeFirstPage(loaded: AuditItem[], fresh: AuditItem[]): AuditItem[] {
  const ids = new Set(fresh.map((it) => it.id))
  return [...fresh, ...loaded.filter((it) => !ids.has(it.id))]
}

/**
 * A newer, not-undone change Claude made to the same item (ux 9.7). While
 * there is one, an older change's undo can be refused (409) because of it:
 * the user acts on the later change first.
 */
export function laterChange(item: AuditItem, items: AuditItem[]): AuditItem | null {
  return (
    items.find(
      (other) =>
        other.id !== item.id &&
        other.target_id === item.target_id &&
        other.undone_at === null &&
        other.created_at > item.created_at,
    ) ?? null
  )
}

/** laterId: the newer change by Claude that was in the way of a 409 (ux 9.7). */
export type UndoState = { undoing: boolean; failure: UndoFailure | null; laterId?: string | null }

/**
 * A 409 caused by a later change ends once that change is undone:
 * the older row gets its Undo back (KP21). Any other 409 stays for the session.
 */
export function settledUndoState(state: UndoState, items: AuditItem[]): UndoState {
  return laterResolved(state, items) ? { undoing: false, failure: null } : state
}

function laterResolved(state: { failure: UndoFailure | null; laterId?: string | null }, items: AuditItem[]): boolean {
  if (state.failure !== 'changed' || !state.laterId) return false
  const later = items.find((it) => it.id === state.laterId)
  // Only undoing it helps: keeping changes no values, so the older undo would still be refused (eng-b on #135).
  return Boolean(later && later.undone_at !== null)
}
