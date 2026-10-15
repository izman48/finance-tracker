/** Card instalment plans (T-12-7b; ux T-12-1 "Plans"; owner D3/D4): which
 *  plans show where, their words, and the plan form. Every figure is the
 *  API's, only formatted; whether a plan is in net worth is the API's too. */
import type { CardPlan, CardPlanBody } from '../services/api'
import { gbp, gbp0 } from './format'

export const plansOnCard = (plans: CardPlan[], cardId: string) => plans.filter((p) => p.card_account_id === cardId)

/** A plan whose card has gone (bank disconnect): standalone debt. */
export const standalonePlans = (plans: CardPlan[]) => plans.filter((p) => p.card_account_id === null)

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
const toGo = (p: CardPlan) => plural(p.instalments_remaining, 'payment to go', 'payments to go')

/** Card settings, line 2: `£100.00 instalment + £5.00 fee · 8 payments to go · £800.00 left`. */
export function settingsPlanLine(p: CardPlan): string {
  const fee = Number(p.fee) > 0 ? ` + ${gbp(Number(p.fee))} fee` : ''
  return `${gbp(Number(p.instalment))} instalment${fee} · ${toGo(p)} · ${gbp(Number(p.balance))} left`
}

/** The card row on Wealth: a chip for plans not in net worth yet, or what
 *  the card balance already includes. */
export function cardPlanChips(plans: CardPlan[]): { unconfirmed: string | null; includes: string | null } {
  const unconfirmed = plans.filter((p) => !p.provider_confirmed).length
  if (unconfirmed > 0) return { unconfirmed: `${plural(unconfirmed, 'plan', 'plans')} not in net worth yet`, includes: null }
  return { unconfirmed: null, includes: plans.length ? `includes ${plural(plans.length, 'plan', 'plans')}` : null }
}

/** A plan row under its card on Wealth, line 2. */
export function wealthPlanLine(p: CardPlan, provider: string): string {
  const monthly = gbp0(Number(p.monthly_total))
  if (!p.provider_confirmed) {
    return `We haven't confirmed whether ${provider} includes plans in the card balance. ${monthly} a month still counts in the card bill.`
  }
  return `${monthly} a month · ${toGo(p)} · inside the card balance`
}

/** Card settings: why the card's unconfirmed plans aren't in net worth, and
 *  that their payments still count (sec mitigation a/b). */
export function unconfirmedNotice(plans: CardPlan[], provider: string): string | null {
  const unconfirmed = plans.filter((p) => !p.provider_confirmed)
  if (unconfirmed.length === 0) return null
  const monthly = unconfirmed.reduce((s, p) => s + Number(p.monthly_total), 0)
  return `Not in net worth yet: we haven't confirmed whether ${provider} includes plans in the card balance. ` +
    `The ${gbp(monthly)} a month still counts in the card bill, your forecast and safe to spend.`
}

// --- the form ---------------------------------------------------------------- #

export interface PlanFormState {
  name: string
  balance: string
  instalment: string
  fee: string
  payments: string
  next_date: string
  apr: string
}
export type PlanField = keyof PlanFormState
export type PlanErrors = Partial<Record<PlanField, string>>

export const blankPlanForm = (today: string): PlanFormState => ({
  name: '', balance: '', instalment: '', fee: '', payments: '', next_date: today, apr: '',
})

export const planFormFor = (p: CardPlan): PlanFormState => ({
  name: p.name, balance: p.balance, instalment: p.instalment, fee: p.fee,
  payments: String(p.instalments_remaining), next_date: p.next_date, apr: '',
})

const num = (s: string) => (s.trim() === '' ? NaN : Number(s))

/** The browser's checks (ux words); the server's 422 stays the authority. */
export function validatePlanForm(f: PlanFormState): PlanErrors {
  const e: PlanErrors = {}
  if (!f.name.trim()) e.name = 'Give it a name.'
  if (!(num(f.balance) >= 0)) e.balance = 'Enter 0 or more.'
  if (!(num(f.instalment) > 0)) e.instalment = 'Enter an amount above 0.'
  if (f.fee.trim() !== '') {
    const fee = num(f.fee)
    if (!(fee >= 0)) e.fee = 'Enter 0 or more.'
    else if (fee > 1000) e.fee = 'Enter an amount from 0 to 1,000.'
  }
  const n = num(f.payments)
  if (!(Number.isInteger(n) && n >= 1 && n <= 120)) e.payments = 'Enter a whole number from 1 to 120.'
  if (!f.next_date) e.next_date = 'Enter the date of the next payment.'
  if (f.apr.trim() !== '' && !(num(f.apr) >= 0 && num(f.apr) <= 100)) e.apr = 'Enter a rate from 0 to 100.'
  return e
}

/** Money goes as the strings typed. A blank APR is left out: the API doesn't
 *  return it, so an edit never clears one entered earlier. */
export function planBody(f: PlanFormState): Omit<CardPlanBody, 'card_account_id'> {
  return {
    name: f.name.trim(), balance: f.balance.trim(), instalment: f.instalment.trim(),
    fee: f.fee.trim() === '' ? '0' : f.fee.trim(), instalments_remaining: Number(f.payments), next_date: f.next_date,
    ...(f.apr.trim() !== '' ? { apr: f.apr.trim() } : {}),
  }
}
