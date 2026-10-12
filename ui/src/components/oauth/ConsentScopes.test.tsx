import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ConsentScopes, { BUDGETS_DESCRIPTION, PLANNING_DESCRIPTION, RULES_DESCRIPTION, SYNC_DESCRIPTION } from './ConsentScopes'

// docs/design/nilu-s08-claude-changes.md (HQ) section 5, K1, K3, K4, K9, K11.

const noop = () => {}

function render(allowRules = true, allowPlanning = false, allowSync = false, allowBudgets = false) {
  return renderToStaticMarkup(
    <ConsentScopes
      allowRules={allowRules}
      allowPlanning={allowPlanning}
      allowSync={allowSync}
      allowBudgets={allowBudgets}
      onRulesChange={noop}
      onPlanningChange={noop}
      onSyncChange={noop}
      onBudgetsChange={noop}
    />,
  )
}

function input(html: string, id: string) {
  return html.match(new RegExp(`<input[^>]*id="${id}"[^>]*>`))?.[0] ?? ''
}

describe('ConsentScopes', () => {
  it('K1: the planning box exists, is unchecked and enabled by default, after the rules box', () => {
    const html = render()
    const planning = input(html, 'allow-planning')
    expect(planning).not.toBe('')
    expect(planning).not.toMatch(/checked/)
    expect(planning).not.toMatch(/disabled/)
    expect(html.indexOf('Change your planned events and commitments')).toBeGreaterThan(html.indexOf('Add rule packs'))
  })

  it('reflects the ticked state', () => {
    expect(input(render(true, true), 'allow-planning')).toMatch(/checked/)
  })

  it('K3: the planning description is linked by aria-describedby and starts with the spec text', () => {
    const html = render()
    const id = input(html, 'allow-planning').match(/aria-describedby="([^"]+)"/)?.[1]
    expect(id).toBeTruthy()
    const described = (html.match(new RegExp(`id="${id}"[^>]*>([^<]*)<`))?.[1] ?? '').replace(/&#x27;/g, "'")
    expect(described).toBe(PLANNING_DESCRIPTION)
    expect(PLANNING_DESCRIPTION.startsWith('Add planned events, remove ones it added, and edit or dismiss commitments.')).toBe(true)
    // D4/D5 (T-08-21b): nothing Claude changes raises either figure until kept.
    expect(PLANNING_DESCRIPTION.endsWith('Nothing it changes raises your safe to spend or savable until you keep it in nilu.')).toBe(true)
    expect(PLANNING_DESCRIPTION).not.toContain('Income it adds never raises your safe to spend.')
  })

  it('K3: the rules description no longer says it cannot edit or delete anything', () => {
    const html = render()
    expect(RULES_DESCRIPTION).toBe(
      "Create new categorisation rule packs. A new pack can recategorise past transactions, but never ones you set by hand. It can't edit or delete your existing rules, and you can remove a pack in Rules.",
    )
    expect(html).not.toContain('edit or delete anything')
  })

  it('the planning tap target is its own row: the label wraps the box, with no negative margins', () => {
    const html = render()
    const row = html.slice(html.lastIndexOf('<li', html.indexOf('id="allow-planning"')))
    const label = row.match(/<label[^>]*for="allow-planning"[^>]*>/)?.[0] ?? ''
    expect(label).not.toBe('')
    expect(row.indexOf(label)).toBeLessThan(row.indexOf('id="allow-planning"'))
    expect(row.slice(0, row.indexOf('</li>'))).not.toMatch(/class="([^"]*\s)?-m[trblxy]?-/)
  })

  it('K4: the planning label is a real <label for>', () => {
    expect(render()).toMatch(/<label[^>]*for="allow-planning"[^>]*>/)
  })

  it('the sync box exists, is unchecked and enabled by default, after the planning box', () => {
    const html = render()
    const sync = input(html, 'allow-sync')
    expect(sync).not.toBe('')
    expect(sync).not.toMatch(/checked/)
    expect(sync).not.toMatch(/disabled/)
    expect(html.indexOf('Refresh your bank data')).toBeGreaterThan(
      html.indexOf('Change your planned events and commitments'),
    )
  })

  it('reflects the ticked sync state', () => {
    expect(input(render(true, false, true), 'allow-sync')).toMatch(/checked/)
  })

  it('the sync box has a real <label for> and its description is linked by aria-describedby', () => {
    const html = render()
    expect(html).toMatch(/<label[^>]*for="allow-sync"[^>]*>/)
    const id = input(html, 'allow-sync').match(/aria-describedby="([^"]+)"/)?.[1]
    expect(id).toBeTruthy()
    const described = (html.match(new RegExp(`id="${id}"[^>]*>([^<]*)<`))?.[1] ?? '').replace(/&#x27;/g, "'")
    expect(described).toBe(SYNC_DESCRIPTION)
    expect(SYNC_DESCRIPTION).toContain('once every 10 minutes')
    expect(SYNC_DESCRIPTION).not.toContain('a day')
  })

  it('K9: the budgets box exists, is unchecked and enabled by default, after the bank refresh box', () => {
    const html = render()
    const budgets = input(html, 'allow-budgets')
    expect(budgets).not.toBe('')
    expect(budgets).not.toMatch(/checked/)
    expect(budgets).not.toMatch(/disabled/)
    expect(html.indexOf('Set and manage your budgets')).toBeGreaterThan(html.indexOf('Refresh your bank data'))
  })

  it('reflects the ticked budgets state', () => {
    expect(input(render(true, false, false, true), 'allow-budgets')).toMatch(/checked/)
  })

  it('K11: the budgets copy is exact, linked by aria-describedby, and the name is its title', () => {
    const html = render()
    expect(BUDGETS_DESCRIPTION).toBe(
      "Set, change, pause, resume or remove your budgets. It's asked to show you a preview before each change. Changes take effect at once, and every one is listed under Changes made by Claude, where you can undo it. Budgets never change your safe to spend.",
    )
    expect(html).toMatch(/<label[^>]*for="allow-budgets"[^>]*>/)
    const box = input(html, 'allow-budgets')
    const described = box.match(/aria-describedby="([^"]+)"/)?.[1]
    const named = box.match(/aria-labelledby="([^"]+)"/)?.[1]
    const text = (id?: string) => (html.match(new RegExp(`id="${id}"[^>]*>([^<]*)<`))?.[1] ?? '').replace(/&#x27;/g, "'")
    expect(text(described)).toBe(BUDGETS_DESCRIPTION)
    expect(text(named)).toBe('Set and manage your budgets')
  })
})
