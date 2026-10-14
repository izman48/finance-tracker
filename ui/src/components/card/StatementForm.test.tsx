import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import StatementForm, { type StatementFormProps } from './StatementForm'

// The add/edit statement form inside the Statement block (ux T-10-0 A.3;
// C-4..C-8). Synthetic values only.
const noop = () => {}
const html = (props: Partial<StatementFormProps>) =>
  renderToStaticMarkup(
    <StatementForm
      mode="add" providerName="Test Bank" replacingProvider={false}
      form={{ statement_balance: '', statement_date: '', due_date: '', minimum_due: '' }}
      errors={{}} saveError={null} saving={false} deleting={false}
      onChange={noop} onSubmit={noop} onCancel={noop} {...props}
    />,
  )
const text = (h: string) =>
  h.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, ' ')

describe('StatementForm', () => {
  it('add: four labelled fields in order, Save and Cancel, no Delete', () => {
    const h = html({})
    const labels = [...h.matchAll(/<label[^>]*for="([^"]+)"[^>]*>([^<]+)</g)].map((m) => [m[1], m[2]])
    expect(labels).toEqual([
      ['statement-balance', 'Statement balance (£)'],
      ['statement-date', 'Statement date'],
      ['statement-due', 'Due date'],
      ['statement-minimum', 'Minimum payment (£), optional'],
    ])
    expect(h).toMatch(/id="statement-balance"[^>]*inputMode="decimal"|inputMode="decimal"[^>]*id="statement-balance"/)
    expect(text(h)).toContain('Add statement')
    expect(h).toMatch(/<button[^>]*type="submit"[^>]*>Save statement<\/button>/)
    expect(h).not.toContain('Delete statement')
  })

  it('edit: heading, Delete, and the replacing line only for a provider statement', () => {
    const h = html({ mode: 'edit', onDelete: noop })
    expect(text(h)).toContain('Edit statement')
    expect(h).toMatch(/<button[^>]*class="btn-danger[^"]*"[^>]*>Delete statement<\/button>/)
    expect(text(h)).not.toContain('You are replacing')
    expect(text(html({ mode: 'edit', onDelete: noop, replacingProvider: true }))).toContain(
      'You are replacing the statement from Test Bank with your own figures.')
  })

  it('C-4/C-5: errors under their fields, marked invalid, with a focusable summary', () => {
    const h = html({ errors: { statement_balance: 'Enter an amount above £0 and up to £1,000,000, like 5584.00.', due_date: 'The due date must be on or after the statement date, and no more than 60 days after it.' } })
    expect(h).toMatch(/role="alert"[^>]*tabindex="-1"[^>]*>Fix the 2 fields below, then save again\./i)
    expect(h).toMatch(/id="statement-balance"[^>]*aria-invalid="true"[^>]*aria-describedby="statement-balance-error"/)
    expect(h).toContain('id="statement-balance-error"')
    expect(h).not.toMatch(/id="statement-date"[^>]*aria-invalid="true"/)
  })

  it('C-7: a duplicate date offers Edit that statement, C-8: any other failure says nothing changed', () => {
    const dup = html({ saveError: 'duplicate', onEditDuplicate: noop })
    expect(text(dup)).toContain('You already have a statement for that date. Edit it instead.')
    expect(dup).toMatch(/<button[^>]*>Edit that statement<\/button>/)
    expect(text(html({ saveError: 'error' }))).toContain(
      'We could not save this statement. Nothing was changed. Check your connection and try again.')
  })

  it('ux on #184: a failed delete says delete, and Delete has an id to return focus to', () => {
    expect(text(html({ mode: 'edit', onDelete: noop, saveError: 'delete' }))).toContain(
      'We could not delete this statement. Nothing was changed. Check your connection and try again.')
    expect(html({ mode: 'edit', onDelete: noop })).toMatch(/<button[^>]*id="statement-delete"/)
  })

  it('saving and deleting disable the buttons and say so', () => {
    expect(html({ saving: true })).toMatch(/<button[^>]*disabled=""[^>]*>Saving…<\/button>/)
    expect(html({ mode: 'edit', onDelete: noop, deleting: true })).toMatch(/<button[^>]*disabled=""[^>]*>Deleting…<\/button>/)
  })
})
