import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ConsentScopes, { PLANNING_DESCRIPTION, RULES_DESCRIPTION } from './ConsentScopes'

// docs/design/nilu-s08-claude-changes.md (HQ) section 5, K1, K3, K4.

const noop = () => {}

function render(allowRules = true, allowPlanning = false) {
  return renderToStaticMarkup(
    <ConsentScopes allowRules={allowRules} allowPlanning={allowPlanning} onRulesChange={noop} onPlanningChange={noop} />,
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
    expect(PLANNING_DESCRIPTION).toContain('Income it adds never raises your safe to spend.')
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
})
