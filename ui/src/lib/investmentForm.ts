/**
 * Add and edit an investment (T-11-5d; ux T-11-2 flow 1 and the holding
 * form states). Pure: the form state, its checks, and the requests a save
 * sends, against an injected client so each case is tested. The server sets
 * every link field; the browser sends the user's terms and, after the
 * "Which bill is this?" picker, the user's choice (owner D2).
 */
import type { Asset, ChooseCandidate, ContributionBody } from '../services/api'
import { latestValue } from './assets'
import { gbp, gbp0 } from './format'

export interface InvestmentFormState {
  name: string
  asset_type: string
  value: string
  growth: string
  contribution: string
  /** "Add £X a month as a commitment". */
  commit: boolean
  pay_from: string
  /** Day of the month, 1 to 28. */
  day: string
}

export type InvestmentField = 'name' | 'value' | 'growth' | 'contribution' | 'pay_from'
export type InvestmentErrors = Partial<Record<InvestmentField, string>>

const MAX = 10_000_000
const MONEY = /^\d+(\.\d{1,2})?$/

export function blankInvestment(today: string, firstCurrentAccount: string | null): InvestmentFormState {
  return {
    name: '', asset_type: 'isa', value: '', growth: '', contribution: '', commit: false,
    pay_from: firstCurrentAccount ?? '', day: String(Math.min(28, Number(today.slice(8, 10)))),
  }
}

/** The form for an existing investment; a linked bill's terms fill the box. */
export function investmentFor(asset: Asset, firstCurrentAccount: string | null): InvestmentFormState {
  const bill = asset.linked_commitment
  const last = asset.valuations[asset.valuations.length - 1]
  return {
    name: asset.name,
    asset_type: asset.asset_type,
    value: last ? last.value : String(latestValue(asset)),
    growth: asset.assumed_growth_pct ?? '',
    contribution: (bill?.amount ?? asset.monthly_contribution) ?? '',
    commit: !!bill,
    pay_from: bill?.pay_from_account_id ?? firstCurrentAccount ?? '',
    day: bill?.next_date ? String(Math.min(28, Number(bill.next_date.slice(8, 10)))) : '1',
  }
}

const amountOf = (raw: string): number | null => {
  const s = raw.trim().replace(/,/g, '')
  return MONEY.test(s) ? Number(s) : null
}

/** The checkbox label (ux I-6): the amount from the box, or disabled. */
export function commitmentLabel(contribution: string): { text: string; enabled: boolean } {
  const n = amountOf(contribution)
  if (n === null || n <= 0) return { text: 'Add a monthly contribution as a commitment', enabled: false }
  return { text: `Add ${Number.isInteger(n) ? gbp0(n) : gbp(n)} a month as a commitment`, enabled: true }
}

/** The next payment: the chosen day this month, or next month once passed. */
export function nextDateForDay(day: string, today: string): string {
  const [y, m, d] = today.split('-').map(Number)
  const want = Number(day)
  const [year, month] = want >= d ? [y, m] : m === 12 ? [y + 1, 1] : [y, m + 1]
  return `${year}-${String(month).padStart(2, '0')}-${String(want).padStart(2, '0')}`
}

/** The field checks (ux "Validation"); messages sit under their field. */
export function checkInvestment(form: InvestmentFormState, hasCurrentAccount: boolean): InvestmentErrors {
  const errors: InvestmentErrors = {}
  if (!form.name.trim()) errors.name = 'Give it a name.'
  const value = amountOf(form.value)
  if (value === null || value > MAX) errors.value = 'Enter the value today, 0 or more.'
  if (form.growth.trim() !== '') {
    const g = Number(form.growth)
    if (!Number.isFinite(g) || g < -100 || g > 50) errors.growth = 'Growth must be between −100% and 50% a year.'
  }
  if (form.contribution.trim() !== '') {
    const c = amountOf(form.contribution)
    if (c === null || c > MAX) errors.contribution = 'Enter 0 or more.'
  }
  if (form.commit && !form.pay_from) {
    errors.pay_from = hasCurrentAccount ? 'Choose an account to pay from.' : 'Connect a bank first, or leave this off.'
  }
  return errors
}

export interface InvestmentClient {
  create: (body: {
    name: string; asset_type: string; value: number; assumed_growth_pct: number | null; monthly_contribution: number | null
  }) => Promise<{ data: { id: string } }>
  update: (id: string, patch: Record<string, unknown>) => Promise<unknown>
  addValuation: (id: string, body: { value: number }) => Promise<unknown>
  setContribution: (id: string, body: ContributionBody) => Promise<unknown>
  stopContribution: (id: string) => Promise<unknown>
}

export type InvestmentOutcome =
  | { kind: 'saved'; assetId: string }
  | { kind: 'invalid'; errors: InvestmentErrors }
  | { kind: 'choose'; assetId: string; candidates: ChooseCandidate[] }
  | { kind: 'message'; message: string }
  | { kind: 'error' }

export const SAVE_ERROR = 'We could not save this. Nothing changed. Try again.'

interface SaveContext {
  asset: Asset | null
  today: string
  hasCurrentAccount: boolean
  /** After the picker: the holding the first save created. */
  createdId?: string
  /** The user's pick in "Which bill is this?" (a bill id or "new"). */
  commitmentChoice?: string
}

/** Save the form: create or patch the holding, then link, change or stop
 *  its bill. Nothing is sent while a check fails. */
export async function saveInvestment(
  client: InvestmentClient, form: InvestmentFormState, ctx: SaveContext,
): Promise<InvestmentOutcome> {
  const errors = checkInvestment(form, ctx.hasCurrentAccount)
  if (Object.keys(errors).length) return { kind: 'invalid', errors }
  const growth = form.growth.trim() === '' ? null : Number(form.growth)
  const contribution = amountOf(form.contribution) ?? 0
  let id = ctx.asset?.id ?? ctx.createdId ?? null
  try {
    if (!id) {
      const res = await client.create({
        name: form.name.trim(), asset_type: form.asset_type, value: amountOf(form.value)!,
        assumed_growth_pct: growth,
        // While linked the bill carries it, never both (sec).
        monthly_contribution: form.commit ? null : contribution || null,
      })
      id = res.data.id
    } else if (ctx.asset) {
      await patchChanges(client, ctx.asset, form, growth, contribution)
    }
    const linked = !!ctx.asset?.linked_commitment
    if (form.commit && contribution > 0 && (!linked || billChanged(ctx.asset!, form, contribution, ctx.today))) {
      await client.setContribution(id, {
        amount: contribution.toFixed(2),
        next_date: nextDateForDay(form.day, ctx.today),
        ...(form.pay_from ? { pay_from_account_id: form.pay_from } : {}),
        ...(ctx.commitmentChoice ? { commitment_choice: ctx.commitmentChoice } : {}),
      })
    } else if (!form.commit && linked) {
      await client.stopContribution(id)
    }
    return { kind: 'saved', assetId: id }
  } catch (e) {
    return outcomeOf(e, id)
  }
}

async function patchChanges(
  client: InvestmentClient, asset: Asset, form: InvestmentFormState, growth: number | null, contribution: number,
) {
  const patch: Record<string, unknown> = {}
  if (form.name.trim() !== asset.name) patch.name = form.name.trim()
  if (form.asset_type !== asset.asset_type) patch.asset_type = form.asset_type
  if (growth !== (asset.assumed_growth_pct == null ? null : Number(asset.assumed_growth_pct))) patch.assumed_growth_pct = growth
  // The legacy figure only for a holding that is and stays unlinked.
  if (!asset.linked_commitment && !form.commit && contribution !== Number(asset.monthly_contribution ?? 0)) {
    patch.monthly_contribution = contribution || null
  }
  if (Object.keys(patch).length) await client.update(asset.id, patch)
  const value = amountOf(form.value)!
  if (value !== latestValue(asset)) await client.addValuation(asset.id, { value })
}

function billChanged(asset: Asset, form: InvestmentFormState, contribution: number, today: string): boolean {
  const bill = asset.linked_commitment!
  return contribution !== Number(bill.amount ?? 0)
    || (!!form.pay_from && form.pay_from !== (bill.pay_from_account_id ?? ''))
    || Number(form.day) !== Math.min(28, Number((bill.next_date ?? nextDateForDay(form.day, today)).slice(8, 10)))
}

type ServerError = { response?: { status?: number; data?: { detail?: unknown } } }

function outcomeOf(e: unknown, id: string | null): InvestmentOutcome {
  const { status, data } = (e as ServerError).response ?? {}
  const detail = data?.detail as { code?: string; candidates?: ChooseCandidate[] } | string | undefined
  if (status === 409 && typeof detail === 'object' && detail?.code === 'choose_commitment' && id) {
    return { kind: 'choose', assetId: id, candidates: detail.candidates ?? [] }
  }
  // Our API's own fixed copy (e.g. a linked bill's guard), shown as text.
  if ((status === 409 || status === 422) && typeof detail === 'string') return { kind: 'message', message: detail }
  return { kind: 'error' }
}

export interface ConfirmCopy { title: string; body: string; confirmLabel: string; cancelLabel: string; danger: boolean }

/** Deleting a holding with a linked bill (ux I-11): the bill stays. */
export function deleteLinkedConfirm(asset: Asset): ConfirmCopy {
  return {
    title: `Delete ${asset.name}?`,
    body: `The bill "${asset.linked_commitment?.label}" stays as a normal bill. You can delete it in Commitments.`,
    confirmLabel: 'Delete', cancelLabel: 'Cancel', danger: true,
  }
}

/** Unticking the box on a linked holding (ux I-10). Opting out deletes the
 *  bill only if the link created it; one the user already had stays as an
 *  ordinary bill (#210 rule 3), so the copy says which. */
export function stopBillConfirm(asset: Asset): ConfirmCopy {
  const label = asset.linked_commitment?.label
  if (asset.linked_commitment?.created === false) {
    return {
      title: 'Stop counting this as a bill?',
      body: `"${label}" stays in your bills as a normal bill, no longer linked to this investment. The monthly contribution stays on the investment.`,
      confirmLabel: 'Unlink bill', cancelLabel: 'Cancel', danger: false,
    }
  }
  return {
    title: 'Stop counting this as a bill?',
    body: `"${label}" will be removed from your bills. The monthly contribution stays on the investment.`,
    confirmLabel: 'Remove bill', cancelLabel: 'Cancel', danger: true,
  }
}
