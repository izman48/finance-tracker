/**
 * Plain-words copy for the "Changes made by Claude" screen (T-08-5; ux spec
 * nilu-s08-claude-changes.md section 1). Pure functions, so every sentence
 * the screen can show is unit-tested.
 *
 * Labels, names and client names come from bank feeds, from Claude and from
 * whoever registered the OAuth client. They are returned as plain strings and
 * rendered as text only.
 */
import { cadenceLabel } from './cadence'
import { dateDayMonth, gbp } from './format'
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
  target_kind: 'planned_event' | 'commitment' | string
  target_id: string
  target_label: string
  changes: AuditChange[]
  undone_at: string | null
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

/** The lines under a row's title (1.4). Fields without a plain-words name are left out. */
export function changeLines(item: AuditItem, accountNames: Record<string, string>): ChangeLine[] {
  const fmt = (field: string, v: AuditValue) => formatValue(field, v, accountNames, item.tool)

  if (item.tool === 'add_planned_event') {
    const lines: ChangeLine[] = []
    for (const field of ['amount', 'start_date']) {
      const c = changeOf(item, field)
      if (c) lines.push({ label: FIELD_LABEL[field], after: fmt(field, c.after) })
    }
    if (isIncome(item)) lines.push({ label: 'Counted in safe to spend', after: 'No, not until it arrives' })
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
