import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ForecastSummary, {
  OVERDRAFT_LINE_LABEL,
  type AccountBreach,
  type ForecastHeadline,
} from './ForecastSummary'

// Per-account breach display (docs/design/forecast-account-breaches.md in HQ).

const monzo: AccountBreach = {
  account_id: 'acc-monzo', account_name: 'Monzo Current', kind: 'overdraft',
  floor: '-500', balance: '-620', date: '2026-10-14',
}
const barclays: AccountBreach = {
  account_id: 'acc-barclays', account_name: 'Barclays Bills', kind: 'zero',
  floor: '0', balance: '-45', date: '2026-10-19',
}
const halifax: AccountBreach = {
  account_id: 'acc-halifax', account_name: 'Halifax', kind: 'zero',
  floor: '-250', balance: '-30', date: '2026-10-22',
}

function render(over: Partial<ForecastHeadline>) {
  const data: ForecastHeadline = {
    min_balance: 120, min_date: '2026-10-14', overdraft_limit: 500,
    breaches: [], account_breaches: [], unassigned_attributed_to: null, ...over,
  }
  return parse(renderToStaticMarkup(<ForecastSummary data={data} />))
}

// The suite runs in node (no DOM library in the project), so read the static
// markup directly. The component keeps the headline a <p> of <span>s for this.
const text = (html: string) =>
  html.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/&quot;/g, '"')

function parse(html: string) {
  const head = html.match(/<p class="([^"]*)" data-testid="forecast-headline">(.*?)<\/p>/)
  return {
    html,
    textContent: text(html),
    headline: { className: head?.[1] ?? '', textContent: text(head?.[2] ?? ''), html: head?.[2] ?? '' },
    items: [...html.matchAll(/<li>(.*?)<\/li>/g)].map((m) => text(m[1])),
    hasList: html.includes('<ul'),
  }
}
type Parsed = ReturnType<typeof parse>

const headline = (el: Parsed) => el.headline
const items = (el: Parsed) => el.items

describe('ForecastSummary', () => {
  it('1, 12: pooled positive but one account breaches', () => {
    const el = render({ breaches: ['overdraft'], account_breaches: [monzo] })
    expect(headline(el).textContent).toContain('Lowest point:')
    expect(headline(el).textContent).not.toContain('exceeds')
    expect(headline(el).textContent).not.toContain('overdraft limit')
    expect(el.textContent).toContain('Your accounts together stay above £0, but one account does not.')
    expect(items(el)).toEqual(['Monzo Current goes past its £500 overdraft limit on 14 Oct (down to -£620.00).'])
    expect(headline(el).className).toContain('text-neg')
    expect(headline(el).html).toContain('<span aria-hidden="true">⚠ </span>')
  })

  it('2: pooled breach of the total limit', () => {
    const el = render({ min_balance: -700, breaches: ['zero', 'overdraft'], account_breaches: [monzo] })
    expect(headline(el).textContent?.endsWith(' — exceeds your total overdraft limit')).toBe(true)
    expect(el.textContent).not.toContain('Your accounts together')
  })

  it('3: pooled dip inside the limit', () => {
    const el = render({ min_balance: -100, breaches: ['zero'] })
    expect(headline(el).textContent?.endsWith(' — dips into overdraft')).toBe(true)
  })

  it('4: pooled below zero with no limits never says overdraft', () => {
    const el = render({ min_balance: -100, overdraft_limit: 0, breaches: ['zero'] })
    expect(headline(el).textContent?.endsWith(' — goes below £0')).toBe(true)
    expect(headline(el).textContent).not.toContain('overdraft')
  })

  it('5: an account with no limit is worded as no overdraft limit set', () => {
    for (const kind of ['zero', 'overdraft']) {
      const el = render({ breaches: ['zero'], account_breaches: [{ ...barclays, kind }] })
      expect(items(el)).toEqual([
        'Barclays Bills goes below £0 on 19 Oct (down to -£45.00). It has no overdraft limit set.',
      ])
    }
  })

  it('6: dipping inside its own limit', () => {
    const el = render({ breaches: ['zero'], account_breaches: [halifax] })
    expect(items(el)).toEqual(['Halifax dips into its overdraft on 22 Oct (down to -£30.00), within its £250 limit.'])
  })

  it('7: several breaches keep API order and are counted in the note', () => {
    const el = render({ breaches: ['overdraft', 'zero'], account_breaches: [monzo, barclays, halifax] })
    expect(items(el).map((t) => t?.split(' ')[0])).toEqual(['Monzo', 'Barclays', 'Halifax'])
    expect(el.textContent).toContain('Your accounts together stay above £0, but 3 accounts do not.')
  })

  it('8: a breach with no account name reads in the plural', () => {
    const el = render({
      min_balance: -45, overdraft_limit: 0, breaches: ['zero'],
      account_breaches: [{ ...barclays, account_id: null, account_name: null }],
    })
    expect(items(el)).toEqual(['Items with no account go below £0 on 19 Oct (down to -£45.00).'])
  })

  it('7b: the accounts count leaves out the no-account entry', () => {
    const el = render({
      breaches: ['overdraft', 'zero'],
      account_breaches: [monzo, halifax, { ...barclays, account_id: null, account_name: null }],
    })
    expect(el.textContent).toContain('Your accounts together stay above £0, but 2 accounts do not.')
  })

  it('spacing: list and notes are spaced for small screens', () => {
    const el = render({
      breaches: ['overdraft'], account_breaches: [monzo], unassigned_attributed_to: 'acc-monzo',
    })
    expect(el.html).toContain('<ul class="text-neg space-y-1')
    expect(el.html.match(/<p class="text-slate-400 mt-1">/g) ?? []).toHaveLength(2)
  })

  it('9: discloses the heuristic on the account it was applied to', () => {
    const el = render({
      breaches: ['overdraft', 'zero'], account_breaches: [monzo, halifax],
      unassigned_attributed_to: 'acc-monzo',
    })
    expect(items(el)[0]?.endsWith('(down to -£620.00). *')).toBe(true)
    expect(items(el)[1]).not.toContain('*')
    const notes = el.textContent?.match(/\* Estimated:/g) ?? []
    expect(notes).toHaveLength(1)
    expect(el.textContent).toContain(
      '* Estimated: items with no account set are counted against Monzo Current, your highest-balance spending account. Set an account on them to make this exact.',
    )
  })

  it('10: no disclosure when the heuristic touched no breaching account', () => {
    for (const attributed of [null, 'acc-other']) {
      const el = render({ breaches: ['overdraft'], account_breaches: [monzo], unassigned_attributed_to: attributed })
      expect(el.textContent).not.toContain('*')
      expect(el.textContent).not.toContain('Estimated:')
    }
  })

  it('11: nothing extra when there is no breach', () => {
    const el = render({})
    expect(el.hasList).toBe(false)
    expect(el.textContent).not.toContain('⚠')
    expect(el.textContent).not.toContain('Your accounts together')
    expect(headline(el).textContent?.endsWith('14 Oct')).toBe(true)
    expect(headline(el).className).toContain('text-slate-400')
  })

  it('13: the dashed chart line is labelled as the total limit', () => {
    expect(OVERDRAFT_LINE_LABEL).toBe('total overdraft limit')
  })
})
