import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { InvestmentFormView, type InvestmentFormViewProps } from './InvestmentForm'
import { blankInvestment } from '../../lib/investmentForm'

// The investment form as markup (ux T-11-2 "Words", holding form states, I-6, I-8, I-12). Synthetic figures.
const props = (over: Partial<InvestmentFormViewProps> = {}): InvestmentFormViewProps => ({
  mode: 'add', name: '',
  form: { ...blankInvestment('2026-10-15', 'acc-1'), name: 'Test ISA', value: '0', growth: '7', contribution: '1000' },
  errors: {}, message: null, saving: false,
  accounts: [{ id: 'acc-1', name: 'Everyday Current' }, { id: 'acc-2', name: 'Bills Current' }],
  candidates: null, choice: null, linkedLabel: null,
  onChange: () => {}, onChoose: () => {}, onBack: () => {}, onSubmit: () => {}, onCancel: () => {}, onDelete: () => {}, ...over,
})
const html = (over: Partial<InvestmentFormViewProps> = {}) => renderToStaticMarkup(<InvestmentFormView {...props(over)} />)
const text = (h: string) => h.replace(/<[^>]+>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ')

describe('InvestmentFormView', () => {
  it('add: title, the five labelled fields, the growth help, Cancel and Save', () => {
    const h = html()
    const t = text(h)
    expect(t).toContain('Add an investment')
    for (const [id, label] of [['investment-name', 'Name'], ['investment-type', 'Type'], ['investment-value-today', 'Value today (£)'],
      ['investment-growth', 'Growth a year (%)'], ['investment-contribution', 'Monthly contribution (£)']]) {
      expect(h).toMatch(new RegExp(`<label[^>]*for="${id}"[^>]*>${label.replace(/[()£%]/g, '\\$&')}</label>`))
    }
    expect(t).toContain('Your own guess. nilu does not look up prices.')
    expect(h).toMatch(/<button[^>]*>Cancel<\/button>/)
    expect(h).toMatch(/<button[^>]*type="submit"[^>]*>Save<\/button>/)
    expect(t).not.toContain('Delete')
  })

  it('types are ISA, Investment, Pension, Crypto', () => {
    const options = [...html().matchAll(/<option value="(isa|investment|pension|crypto)"[^>]*>([^<]+)</g)].map((m) => m[2])
    expect(options).toEqual(['ISA', 'Investment', 'Pension', 'Crypto'])
  })

  it('I-6: the checkbox names the amount and explains the rule; disabled without an amount', () => {
    const t = text(html())
    expect(t).toContain('Add £1,000 a month as a commitment')
    expect(t).toContain('Counts like a bill: it lowers safe to spend and your Cashflow forecast. Your net worth stays the same, because the money moves into the investment.')
    const off = html({ form: { ...props().form, contribution: '' } })
    expect(text(off)).toContain('Add a monthly contribution as a commitment')
    expect(off).toMatch(/<input[^>]*type="checkbox"[^>]*disabled=""/)
  })

  it('ticked: Pay from (current accounts) and Day 1 to 28 follow it, with aria-expanded and aria-controls', () => {
    const h = html({ form: { ...props().form, commit: true } })
    expect(h).toMatch(/type="checkbox"[^>]*aria-expanded="true"[^>]*aria-controls="investment-bill-fields"/)
    expect(h).toContain('id="investment-bill-fields"')
    expect(text(h)).toContain('Pay from')
    expect(text(h)).toContain('Everyday Current')
    const days = [...h.matchAll(/<option value="(\d+)"[^>]*>\d+<\/option>/g)].map((m) => Number(m[1]))
    expect(days).toEqual(Array.from({ length: 28 }, (_, i) => i + 1))
    expect(html()).not.toContain('id="investment-bill-fields"')
  })

  it('I-12: a field error sits under its field, tied by aria-describedby', () => {
    const h = html({ errors: { growth: 'Growth must be between −100% and 50% a year.' } })
    expect(h).toMatch(/id="investment-growth"[^>]*aria-invalid="true"[^>]*aria-describedby="investment-growth-error"/)
    expect(text(h)).toContain('Growth must be between −100% and 50% a year.')
  })

  it('I-13: the server error above the buttons', () => {
    expect(text(html({ message: 'We could not save this. Nothing changed. Try again.' }))).toContain('We could not save this. Nothing changed. Try again.')
  })

  it('saving: Save reads Saving… and is disabled', () => {
    expect(html({ saving: true })).toMatch(/<button[^>]*type="submit"[^>]*disabled=""[^>]*>Saving…<\/button>/)
  })

  it('edit: the holding name as title, Delete, and the linked bill', () => {
    const t = text(html({ mode: 'edit', name: 'Test ISA', linkedLabel: 'Test ISA contribution' }))
    expect(t).toContain('Test ISA')
    expect(t).toContain('Delete')
    expect(t).toContain('Test ISA contribution')
  })

  it('I-8: the picker lists each bill and a new one, none chosen, Save disabled until one is', () => {
    const candidates = [{ id: 'c9', label: 'ISA DD', amount: '1000.00', cadence: 'monthly', interval_days: null, next_date: '2026-10-28' }]
    const h = html({ candidates, form: { ...props().form, commit: true, day: '28' } })
    const t = text(h)
    expect(t).toContain('Which bill is this?')
    expect(t).toContain('Pick the one that pays Test ISA, so it only counts once.')
    expect(t).toContain('ISA DD')
    expect(t).toContain('£1,000.00 monthly · next 28 Oct')
    expect(t).toContain('None of these, add a new bill')
    expect(t).toContain('nilu adds "Test ISA contribution", £1,000.00 monthly on the 28th')
    expect(h).not.toMatch(/type="radio"[^>]*checked/)
    expect(h).toMatch(/<button[^>]*aria-disabled="true"[^>]*disabled=""[^>]*>Save<\/button>/)
    expect(t).toContain('Choose one to continue.')
    expect(h).toMatch(/<button[^>]*>Back<\/button>/)
  })
})
