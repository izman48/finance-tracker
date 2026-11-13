/** The fixed sample account shown while "Anonymize numbers" is on.
 *
 *  A hand-authored, self-contained fake financial world — fake banks,
 *  merchants and figures with no relation to the real user. Every derived
 *  view (spending totals, the drill-down list, the balance sheet, net worth)
 *  is computed from the ONE ledger below, so it all reconciles by
 *  construction. Dates roll relative to today so it never looks stale; the
 *  structure is otherwise identical every time.
 *
 *  sampleAccount.test.ts guards the reconciliation (headline == sum of parts).
 */

import {
  SAMPLE_BUDGETS_MONTHLY, sampleBudgetHistory, sampleBudgetList, sampleBudgetNudges, sampleBudgetProjection, type BudgetLedgerTx, type SampleScheduledBill,
} from './sampleBudgets'
import { sampleInvestmentGraph } from './sampleInvestments'

// --- shape helpers --------------------------------------------------------- #

const nowMinus = (days: number) => {
  const d = new Date()
  d.setDate(d.getDate() - days)
  d.setHours(9, 0, 0, 0)
  return d
}
const nowPlus = (days: number) => nowMinus(-days)
const isoDate = (d: Date) => d.toISOString().slice(0, 10)
const isoDateTime = (d: Date) => d.toISOString()

type Role = 'spending' | 'savings' | 'credit'

interface SampleAccount {
  id: string
  display_name: string
  provider_name: string
  account_type: string
  role: Role
  current_balance: number
  overdraft_limit: number | null
}

interface SampleTx {
  id: string
  account_id: string
  transaction_type: 'debit' | 'credit'
  amount: number
  description: string
  merchant_name: string
  category: string
  is_recurring: boolean
  is_commitment: boolean
  excluded_reason: 'internal_transfer' | 'card_payment' | null
  daysAgo: number
}

// --- the fake world -------------------------------------------------------- #

const ACCOUNTS: SampleAccount[] = [
  { id: 'sa1', display_name: 'Everly Current', provider_name: 'Everly Bank', account_type: 'TRANSACTION', role: 'spending', current_balance: 2480.55, overdraft_limit: 500 },
  { id: 'sa2', display_name: 'Cardinal Everyday', provider_name: 'Cardinal', account_type: 'TRANSACTION', role: 'spending', current_balance: 940.2, overdraft_limit: 0 },
  { id: 'sa3', display_name: 'Acorn Saver', provider_name: 'Acorn Bank', account_type: 'SAVINGS', role: 'savings', current_balance: 12000, overdraft_limit: null },
  { id: 'sa4', display_name: 'Harbor Rewards', provider_name: 'Harbor Financial', account_type: 'CREDIT_CARD', role: 'credit', current_balance: -640.3, overdraft_limit: null },
]
const ROLE: Record<string, Role> = Object.fromEntries(ACCOUNTS.map((a) => [a.id, a.role]))

// Investments (T-11-8, ux T-11-2 "Demo mode"): each with its own growth %;
// the ISA's £400 a month is a linked bill, so it is a commitment in Cashflow
// and safe to spend, and the holding takes it (never also as its own figure).
const ASSETS = [
  { id: 'sas1', name: 'Sample ISA', asset_type: 'isa', value: 18500, growth: 7, monthly: 400, linked: true },
  { id: 'sas2', name: 'Sample Pension', asset_type: 'pension', value: 24000, growth: 5, monthly: 0, linked: false },
  { id: 'sas3', name: 'Sample Crypto', asset_type: 'crypto', value: 1200, growth: 0, monthly: 0, linked: false },
  // The house its mortgage names (T-12-7b, ux "Demo mode"): equity is display only.
  { id: 'sas4', name: 'Sample House', asset_type: 'property', value: 250000, growth: 3, monthly: 0, linked: false },
]
const INVESTMENT_TYPES = new Set(['isa', 'investment', 'pension', 'crypto'])
const isInvestmentAsset = (a: (typeof ASSETS)[number]) => INVESTMENT_TYPES.has(a.asset_type)
const CONTRIBUTION = { id: 'sc-isa-contribution', label: 'Sample ISA contribution', amount: 400, nextIn: 5, account: 'sa1' }
/** Entered values: about 10% lower six months ago, then the value today. */
const assetValuations = (a: (typeof ASSETS)[number]) => [
  // The house is entered at one value, so it adds no growth to the sample's headline.
  { id: `${a.id}-v0`, date: isoDate(nowMinus(180)), value: a.asset_type === 'property' ? a.value : Math.round(a.value * (a.value < 0 ? 1.15 : 0.9)) },
  { id: `${a.id}-v1`, date: isoDate(nowMinus(40)), value: a.value },
]

// Loans and finance (T-10-10): entered terms plus the API's derived figures,
// fixed so the sample reconciles (net worth subtracts LIABILITIES_TOTAL).
const LIABILITIES = [
  {
    id: 'sl1', kind: 'finance', lender: 'Willow Home Finance', balance: '1500.00', apr: '19.90', payment: '100.00',
    cadence: 'monthly', interest_remaining: '139.41', payments_remaining: 17, end_date: null, payoff_days: 480,
  },
  {
    id: 'sl2', kind: 'loan', lender: 'Northgate Motor Loans', balance: '6800.00', apr: '8.90', payment: '240.00',
    cadence: 'monthly', interest_remaining: '882.20', payments_remaining: 32, end_date: null, payoff_days: 960,
  },
  {
    id: 'sl3', kind: 'mortgage', lender: 'Sample Bank', balance: '120000.00', apr: '4.50', payment: '780.00',
    cadence: 'monthly', interest_remaining: '62436.00', payments_remaining: 234, end_date: null, payoff_days: 7110,
  },
] as const
// The mortgage's property and bill (T-12-7b): the bill is a linked commitment,
// edited through the mortgage, and leaves cash after payday.
const MORTGAGE_PROPERTY = 'sas4'
const MORTGAGE_BILL = { id: 'sc-mortgage', label: 'Sample Bank mortgage payment', amount: 780, nextIn: 27 }
const LIABILITIES_TOTAL = LIABILITIES.reduce((s, l) => s + Number(l.balance), 0)

// A card instalment plan (T-12-7b; lead 2026-10-15): one plan on Harbor
// Rewards from a provider not yet confirmed, so it is never in net worth or
// Total owed (D4), while its instalment + fee leaves on the card's pay day
// with the card payment and counts in safe to spend (sec mitigation b).
const CARD_PLAN = { id: 'scp1', card: 'sa4', name: 'Laptop plan', instalment: 100, fee: 5, remaining: 8, firstIn: 8 }
const PLAN_MONTHLY = CARD_PLAN.instalment + CARD_PLAN.fee

function cardPlansResponse() {
  const p = CARD_PLAN
  return [{
    id: p.id, card_account_id: p.card, card_name: 'Harbor Rewards', name: p.name,
    balance: (p.instalment * p.remaining).toFixed(2), instalment: p.instalment.toFixed(2), fee: p.fee.toFixed(2),
    instalments_remaining: p.remaining, next_date: isoDate(nowPlus(p.firstIn)),
    final_date: isoDate(nowPlus(p.firstIn + 30 * (p.remaining - 1))), monthly_total: PLAN_MONTHLY.toFixed(2),
    in_net_worth: false, provider_confirmed: false,
  }]
}

// One authored ledger everything else is computed from. Spans ~6 months (a
// repeating monthly pattern + slight per-month variation) so the period/date
// controls actually change the data, not just a shallow 30-day window.
function buildLedger(): SampleTx[] {
  const out: SampleTx[] = []
  const p = (
    desc: string, merchant: string, category: string, amount: number,
    type: 'debit' | 'credit', account: string, daysAgo: number,
    opts?: { commitment?: boolean; recurring?: boolean; excluded?: SampleTx['excluded_reason'] },
  ) => out.push(t(desc, merchant, category, Math.round(amount * 100) / 100, type, account, daysAgo, opts))

  for (let m = 0; m < 6; m++) {
    const base = m * 30
    const v = m % 3 // deterministic monthly variation
    // income + recurring commitments
    p('Salary', 'Sterling Payroll', 'Income', 3200, 'credit', 'sa1', base + 6, { commitment: true, recurring: true })
    p('Rent', 'Northgate Lettings', 'Housing', 1100, 'debit', 'sa1', base + 5, { commitment: true, recurring: true })
    p('Gym', 'Ironvale Fitness', 'Health', 32, 'debit', 'sa1', base + 4, { commitment: true, recurring: true })
    p('Phone', 'Beacon Mobile', 'Bills', 20, 'debit', 'sa1', base + 8, { commitment: true, recurring: true })
    p('Netflix', 'Verano Media', 'Subscriptions', 12.99, 'debit', 'sa4', base + 10, { commitment: true, recurring: true })
    p('Spotify', 'Larkfield Audio', 'Subscriptions', 11.99, 'debit', 'sa4', base + 12, { commitment: true, recurring: true })
    // discretionary — varies month to month so ranges differ
    p('Fernwood Grocers', 'Fernwood Grocers', 'Groceries', 54.2 + v * 4, 'debit', 'sa1', base + 1)
    p('Oakvale Market', 'Oakvale Market', 'Groceries', 62.4 - v * 3, 'debit', 'sa2', base + 3)
    p('Fernwood Grocers', 'Fernwood Grocers', 'Groceries', 38.1 + v * 2, 'debit', 'sa1', base + 16)
    p('Verano Bakehouse', 'Verano Bakehouse', 'Eating out', 14.5 + v, 'debit', 'sa4', base + 2)
    p('Redgate Kitchen', 'Redgate Kitchen', 'Eating out', 28, 'debit', 'sa1', base + 14)
    p('Cobalt Coffee', 'Cobalt Coffee', 'Eating out', 3.6, 'debit', 'sa2', base + 7)
    p('Solent Transit', 'Solent Transit', 'Transport', 8.1, 'debit', 'sa1', base + 1)
    p('Solent Transit', 'Solent Transit', 'Transport', 8.1, 'debit', 'sa1', base + 9)
    p('Bexley Goods', 'Bexley Goods', 'Shopping', 45 + v * 25, 'debit', m % 2 ? 'sa4' : 'sa2', base + 11)
  }
  // The PRD's paid-back example (T-03-6, AC-33): a shared dinner on the card,
  // two friends paying their share back, both marked by Claude (SAMPLE_MARKS).
  p('Harbour Pizzeria', 'Harbour Pizzeria', 'Eating out', 200, 'debit', 'sa4', 5)
  p('S PATEL DINNER', 'S PATEL', 'Other', 60, 'credit', 'sa1', 3)
  p('J OKAFOR', 'J OKAFOR', 'Other', 50, 'credit', 'sa1', 2)
  // noise, in the recent month — shown, labelled, opt-in to hide
  p('Payment to Harbor Rewards', 'Harbor Financial', 'Transfers', 300, 'debit', 'sa1', 6, { excluded: 'card_payment' })
  p('Transfer to Acorn Saver', 'Acorn Bank', 'Transfers', 500, 'debit', 'sa1', 6, { excluded: 'internal_transfer' })
  p('Transfer from Everly', 'Everly Bank', 'Transfers', 500, 'credit', 'sa3', 6, { excluded: 'internal_transfer' })
  return out
}
const L: SampleTx[] = buildLedger()

// Claude's marks on the dinner (T-03-6): what each paid back, by the API's rule (both fit, so both apply).
const txId = (merchant: string) => (L.find((x) => x.merchant_name === merchant) as SampleTx).id
const SAMPLE_MARKS = [
  { id: 'sm1', audit_id: 'sample-mark-1', credit: txId('S PATEL'), spend: txId('Harbour Pizzeria'), amount: 60 },
  { id: 'sm2', audit_id: 'sample-mark-2', credit: txId('J OKAFOR'), spend: txId('Harbour Pizzeria'), amount: 50 },
]
const byId = (id: string) => L.find((x) => x.id === id) as SampleTx
const markLabel = (m: (typeof SAMPLE_MARKS)[number]) =>
  `${byId(m.credit).merchant_name} £${m.amount.toFixed(2)}, ${byId(m.spend).merchant_name}`
/** What a purchase's marks net: it counts as its amount less this. */
const paidBackOn = (txId: string) => SAMPLE_MARKS.filter((m) => m.spend === txId).reduce((t, m) => t + m.amount, 0)

function markRow(m: (typeof SAMPLE_MARKS)[number]) {
  const credit = byId(m.credit)
  const spend = byId(m.spend)
  return {
    mark_id: m.id, credit_id: m.credit, spend_id: m.spend, category: null, amount: m.amount.toFixed(2),
    label: markLabel(m), created_via: 'mcp', applied: true, cycle_closed: false, audit_id: m.audit_id,
    payer: credit.merchant_name, against: spend.merchant_name,
    credit_date: isoDate(nowMinus(credit.daysAgo)), spend_date: isoDate(nowMinus(spend.daysAgo)),
  }
}

/** GET /audit: Claude's two marks, for "Changes made by Claude". */
function auditResponse() {
  return {
    items: SAMPLE_MARKS.map((m) => ({
      id: m.audit_id, created_at: isoDateTime(nowMinus(1)), tool: 'mark_paid_back', batch_id: 'sample-mark-batch',
      client_name: 'Claude', connection_created_at: isoDateTime(nowMinus(30)), target_kind: 'repayment_mark',
      target_id: m.id, target_label: markLabel(m), undone_at: null,
      changes: [
        { field: 'amount', before: null, after: m.amount.toFixed(2) },
        { field: 'spend_transaction_id', before: null, after: m.spend },
        { field: 'active', before: null, after: true },
      ],
    })),
    next_cursor: null,
  }
}


function t(
  desc: string, merchant: string, category: string, amount: number,
  type: 'debit' | 'credit', account_id: string, daysAgo: number,
  opts: { commitment?: boolean; recurring?: boolean; excluded?: SampleTx['excluded_reason'] } = {},
): SampleTx {
  return {
    id: `stx-${desc}-${daysAgo}-${account_id}`.replace(/\s+/g, '_'),
    account_id, transaction_type: type, amount, description: desc, merchant_name: merchant,
    category, is_recurring: !!opts.recurring, is_commitment: !!opts.commitment,
    excluded_reason: opts.excluded ?? null, daysAgo,
  }
}

const CURRENCY = 'GBP'

// --- transactions endpoint (filters applied to the fixed ledger) ----------- #

interface TxQuery {
  page?: number; page_size?: number; account_id?: string; search?: string
  category?: string[]; merchant?: string; type?: string; date_from?: string; date_to?: string
  min_amount?: number; max_amount?: number; include_excluded?: boolean
  hide_transfers?: boolean; hide_card_payments?: boolean
  exclude_commitments?: boolean; kind?: string; sort?: string; sort_dir?: string
}

const isPurchase = (tx: SampleTx) =>
  tx.transaction_type === 'debit' && !tx.excluded_reason &&
  (ROLE[tx.account_id] === 'spending' || ROLE[tx.account_id] === 'credit')

const purchaseKind = (tx: SampleTx) => (ROLE[tx.account_id] === 'credit' ? 'credit' : 'cash')

// Budgets (T-11-8) read the same ledger: purchases count, commitments,
// transfers and card payoffs are named as not counted.
const BUDGET_LEDGER: BudgetLedgerTx[] = L.map((tx) => ({
  category: tx.category, amount: tx.amount - paidBackOn(tx.id), daysAgo: tx.daysAgo, label: tx.description,
  kind: tx.excluded_reason === 'internal_transfer' ? 'transfer'
    : tx.excluded_reason === 'card_payment' ? 'card_payoff'
    : !isPurchase(tx) ? 'other'
    : tx.is_commitment ? 'commitment' : 'purchase',
}))
// Before marks: what left would be without them, for the dotted-line copy.
const GROSS_BUDGET_LEDGER: BudgetLedgerTx[] = BUDGET_LEDGER.map((b, i) => ({ ...b, amount: L[i].amount }))
const SAMPLE_PAID_BACK = SAMPLE_MARKS.map((m) => ({
  label: markLabel(m), amount: m.amount, against: byId(m.spend).merchant_name, category: byId(m.spend).category,
  daysAgo: byId(m.spend).daysAgo,
}))
const PAYDAY_AGO = Math.min(...L.filter((x) => x.transaction_type === 'credit' && x.is_commitment).map((x) => x.daysAgo))

function txResponse(q: TxQuery) {
  const cats = q.category && q.category.length ? new Set(q.category) : null
  const fromT = q.date_from ? new Date(q.date_from + 'T00:00:00').getTime() : null
  const toT = q.date_to ? new Date(q.date_to + 'T23:59:59').getTime() : null
  const filtered = L.filter((tx) => {
    // Nothing hidden by default; opt-in hides mirror the backend.
    if (q.include_excluded === false && tx.excluded_reason) return false
    if (q.hide_transfers && tx.excluded_reason === 'internal_transfer') return false
    if (q.hide_card_payments && tx.excluded_reason === 'card_payment') return false
    if (q.exclude_commitments && tx.is_commitment) return false
    if (q.account_id && tx.account_id !== q.account_id) return false
    const when = nowMinus(tx.daysAgo).getTime()
    if (fromT != null && when < fromT) return false
    if (toT != null && when > toT) return false
    if (q.search) {
      const hay = `${tx.description} ${tx.merchant_name}`.toLowerCase()
      if (!hay.includes(q.search.toLowerCase())) return false
    }
    if (cats && !cats.has(tx.category)) return false
    if (q.merchant && (tx.merchant_name || tx.description) !== q.merchant) return false
    if (q.type === 'debit' && tx.transaction_type !== 'debit') return false
    if (q.type === 'credit' && tx.transaction_type !== 'credit') return false
    if (q.min_amount != null && Math.abs(tx.amount) < q.min_amount) return false
    if (q.max_amount != null && Math.abs(tx.amount) > q.max_amount) return false
    if (q.kind === 'money_out') {
      if (!isMoneyOut(tx)) return false
    } else if (q.kind) {
      if (!isPurchase(tx)) return false
      const k = purchaseKind(tx)
      if (q.kind === 'cash' && k !== 'cash') return false
      if (q.kind === 'credit' && k !== 'credit') return false
    }
    return true
  })

  const rev = q.sort_dir !== 'asc'
  filtered.sort((a, b) =>
    q.sort === 'amount'
      ? (Math.abs(a.amount) - Math.abs(b.amount)) * (rev ? -1 : 1)
      : (a.daysAgo - b.daysAgo) * (rev ? 1 : -1),
  )

  const page = q.page ?? 1
  const size = q.page_size ?? 50
  const slice = filtered.slice((page - 1) * size, page * size)
  return {
    items: slice.map(txItem),
    total: filtered.length,
    page,
    page_size: size,
  }
}

function txItem(tx: SampleTx) {
  return {
    id: tx.id,
    account_id: tx.account_id,
    transaction_type: tx.transaction_type,
    amount: tx.amount,
    currency: CURRENCY,
    description: tx.description,
    merchant_name: tx.merchant_name,
    category: tx.category,
    subcategory: null,
    is_recurring: tx.is_recurring,
    is_commitment: tx.is_commitment,
    is_financed: false,
    excluded_reason: tx.excluded_reason,
    counts_as_override: null,
    counts_as_locked: false,
    transaction_date: isoDateTime(nowMinus(tx.daysAgo)),
    paid_back_amount: tx.transaction_type === 'debit' ? paidBackOn(tx.id).toFixed(2) : null,
    paid_back_marks: SAMPLE_MARKS.filter((m) => m.credit === tx.id || m.spend === tx.id).map(markRow),
  }
}

// --- spending endpoint (purchases logic over the ledger, same predicate) --- #

function spendingRange(period: string, frm?: string, to?: string): [number, number] {
  // Returns [maxDaysAgo, minDaysAgo] inclusive window in "days ago" space.
  if (period === 'custom' && frm && to) {
    // Date-only arithmetic (UTC midnights) so calendar bounds are exact —
    // Date.now() deltas drift a day across timezones.
    const dayDiff = (iso: string) => {
      const [y, m, d] = iso.split('-').map(Number)
      const t = new Date()
      return Math.round((Date.UTC(t.getFullYear(), t.getMonth(), t.getDate()) - Date.UTC(y, m - 1, d)) / 864e5)
    }
    const f = dayDiff(frm)
    const tt = dayDiff(to)
    return [Math.max(f, tt), Math.min(f, tt)]
  }
  if (period === 'this_month') return [new Date().getDate() - 1, 0]
  if (period === 'last_30') return [30, 0]
  // since_payday — since the most recent income row
  const lastIncome = Math.min(...L.filter((x) => x.transaction_type === 'credit' && x.is_commitment).map((x) => x.daysAgo))
  return [lastIncome, 0]
}

const isMoneyOut = (tx: SampleTx) => ROLE[tx.account_id] === 'spending' && tx.transaction_type === 'debit'

function spendingResponse(q: {
  period?: string; frm?: string; to?: string; exclude_commitments?: boolean
  lens?: string; hide_transfers?: boolean; hide_card_payments?: boolean
  account_id?: string; kind?: string
}) {
  const period = q.period ?? 'since_payday'
  const lens = q.lens ?? 'money_out'
  const [maxAgo, minAgo] = spendingRange(period, q.frm, q.to)
  // account_id / kind scope the breakdown to the active drill (mirrors backend).
  const kindScope = q.kind === 'cash' || q.kind === 'credit' ? q.kind : null
  const inScope = (tx: SampleTx) => (!q.account_id || tx.account_id === q.account_id)
  const inRange = (tx: SampleTx) => tx.daysAgo <= maxAgo && tx.daysAgo >= minAgo
  const round = (n: number) => Math.round(n * 100) / 100

  const byCat = new Map<string, { total: number; count: number }>()
  const byMerch = new Map<string, number>()
  const tally = (tx: SampleTx, amount = tx.amount) => {
    const c = byCat.get(tx.category) ?? { total: 0, count: 0 }
    c.total += amount
    c.count += 1
    byCat.set(tx.category, c)
    byMerch.set(tx.merchant_name, (byMerch.get(tx.merchant_name) ?? 0) + amount)
  }

  let total = 0
  let cash = 0
  let credit = 0
  let composition: Record<string, string> | null = null

  if (lens === 'purchases') {
    for (const tx of L) {
      if (!isPurchase(tx) || !inRange(tx) || !inScope(tx) || (q.exclude_commitments && tx.is_commitment)) continue
      if (kindScope && purchaseKind(tx) !== kindScope) continue
      const counted = tx.amount - paidBackOn(tx.id) // friends' marked repayments (T-03-6)
      if (purchaseKind(tx) === 'credit') credit += counted
      else cash += counted
      tally(tx, counted)
    }
    total = cash + credit
  } else {
    const comp = { card_repayments: 0, transfers: 0, commitments: 0, other: 0 }
    for (const tx of L) {
      if (!isMoneyOut(tx) || !inRange(tx) || !inScope(tx)) continue
      if (q.hide_transfers && tx.excluded_reason === 'internal_transfer') continue
      if (q.hide_card_payments && tx.excluded_reason === 'card_payment') continue
      if (q.exclude_commitments && tx.is_commitment) continue
      total += tx.amount
      if (tx.excluded_reason === 'internal_transfer') comp.transfers += tx.amount
      else if (tx.excluded_reason === 'card_payment') comp.card_repayments += tx.amount
      else if (tx.is_commitment) comp.commitments += tx.amount
      else comp.other += tx.amount
      tally(tx)
    }
    composition = {
      card_repayments: String(round(comp.card_repayments)),
      transfers: String(round(comp.transfers)),
      commitments: String(round(comp.commitments)),
      other: String(round(comp.other)),
    }
  }

  return {
    lens,
    period,
    // Custom ranges echo the requested dates verbatim, like the real backend.
    period_start: period === 'custom' && q.frm ? q.frm : isoDate(nowMinus(maxAgo)),
    period_end: period === 'custom' && q.to ? q.to : isoDate(nowMinus(minAgo)),
    total_spent: String(round(total)),
    charged_to_credit: String(round(credit)),
    paid_from_cash: String(round(cash)),
    composition,
    by_category: [...byCat.entries()]
      .map(([category, v]) => ({ category, total: String(round(v.total)), count: v.count }))
      .sort((a, b) => Number(b.total) - Number(a.total)),
    top_merchants: [...byMerch.entries()]
      .map(([merchant, total]) => ({ merchant, total: String(round(total)) }))
      .sort((a, b) => Number(b.total) - Number(a.total)),
  }
}

// --- the rest, hand-authored to stay coherent with the above --------------- #

const AVAILABLE_CASH = 2480.55 + 940.2 // spending accounts
const SAVINGS_TOTAL = 12000
const CREDIT_OWED = 640.3
// The sample card is on statement_balance, paid weekly (T-12-7a): £550.30
// billed on its last statement goes on the next pay day, in 3 days, and the
// £90.00 spent since on the one after, a week later. Both are among the
// first rows of Coming up, so demo shows "Harbor Rewards bill" and
// "Harbor Rewards bill (projected)" (ux on #242).
const STATEMENT_DUE_IN = 3
const SPENT_SINCE_DUE_IN = STATEMENT_DUE_IN + 7
const SPENT_SINCE = 90
const STATEMENT_OWED = Math.round((CREDIT_OWED - SPENT_SINCE) * 100) / 100
const SAMPLE_REPAYMENTS = [
  { due_in: STATEMENT_DUE_IN, amount: STATEMENT_OWED, projected: false, kind: 'statement' as const },
  { due_in: SPENT_SINCE_DUE_IN, amount: SPENT_SINCE, projected: true, kind: 'spent_since' as const },
]

/** The card's next weekly pay day on or after `day` days from now. */
const cardPayDayFrom = (day: number) =>
  day <= STATEMENT_DUE_IN ? STATEMENT_DUE_IN : STATEMENT_DUE_IN + 7 * Math.ceil((day - STATEMENT_DUE_IN) / 7)

/** Every card repayment the sample's engine would send: the two Harbor bills
 *  and the Laptop plan's instalment + fee, each on the card's next pay day on
 *  or after its instalment date (T-12-5b). Not projected: a plan's amount is
 *  fixed. */
function cardRepaymentsDue() {
  const plan = Array.from({ length: CARD_PLAN.remaining }, (_, k) => ({
    due_in: cardPayDayFrom(CARD_PLAN.firstIn + 30 * k), amount: PLAN_MONTHLY, projected: false,
    label: `${CARD_PLAN.name} instalment`,
  }))
  return [...SAMPLE_REPAYMENTS.map((r) => ({ ...r, label: 'Harbor Rewards' })), ...plan]
}
const ASSETS_TOTAL = ASSETS.reduce((s, a) => s + a.value, 0)
const INVESTMENTS_TOTAL = ASSETS.filter(isInvestmentAsset).reduce((s, a) => s + a.value, 0)
const PROPERTY_TOTAL = ASSETS.filter((a) => a.asset_type === 'property').reduce((s, a) => s + a.value, 0)
const NET_WORTH = AVAILABLE_CASH + SAVINGS_TOTAL + ASSETS_TOTAL - CREDIT_OWED - LIABILITIES_TOTAL

function summaryResponse() {
  // rent + phone + subs + gym, the ISA contribution (a linked bill), and the
  // card repayments and the card plan's instalments due before payday, as
  // the API counts them (T-12-7a, T-12-5b).
  const cardBeforePayday = cardRepaymentsDue().filter((r) => r.due_in < 24).reduce((t, r) => t + r.amount, 0)
  const committed = Math.round((1100 + 20 + 12.99 + 11.99 + 32 + CONTRIBUTION.amount + cardBeforePayday) * 100) / 100
  return {
    available_cash: AVAILABLE_CASH,
    overdraft_cushion: 500,
    credit_owed: CREDIT_OWED,
    savings_total: SAVINGS_TOTAL,
    assets_total: ASSETS_TOTAL,
    investments_total: INVESTMENTS_TOTAL.toFixed(2),
    liabilities_total: LIABILITIES_TOTAL,
    // Cards plus loans, as the API sums it (T-10-14a).
    total_owed: (CREDIT_OWED + LIABILITIES_TOTAL).toFixed(2),
    net_worth: NET_WORTH,
    committed_before_payday: committed,
    safe_to_spend: Math.round((AVAILABLE_CASH - committed) * 100) / 100,
    savable: 820,
    next_payday: isoDate(nowPlus(24)),
    // As the API sends them (T-12-7a): "Harbor Rewards bill" for the
    // statement, "Harbor Rewards bill (projected)" for the spend since it.
    next_repayments: SAMPLE_REPAYMENTS.map((r) => ({
      account_id: 'sa4', label: 'Harbor Rewards', amount: r.amount, due_date: isoDate(nowPlus(r.due_in)),
      projected: r.projected, parts: [{ kind: r.kind, amount: r.amount }],
    })),
    accounts: ACCOUNTS.map((a) => ({
      id: a.id, display_name: a.display_name, provider_name: a.provider_name,
      account_type: a.account_type, role: a.role, current_balance: a.current_balance,
      credit_owed: a.role === 'credit' ? -a.current_balance : null,
      // T-10-14: the sample card's statement, the same bill as next_repayments.
      overdraft_limit: a.overdraft_limit, repayment_cadence: a.role === 'credit' ? 'weekly' : null,
      repayment_day: null, repayment_interval_months: null, repayment_anchor_date: a.role === 'credit' ? isoDate(nowPlus(STATEMENT_DUE_IN)) : null,
      repayment_strategy: a.role === 'credit' ? 'statement_balance' : null,
      repayment_fixed_amount: null, repayment_installments: null, pay_from_account_id: null,
      // The card's statement, as statementsResponse has it (T-10-14a).
      ...(a.role === 'credit' ? { statement: sampleStatement() } : {}),
    })),
  }
}

// Subscriptions the demo forecast schedules (T-24-5b): the same list feeds
// budgets' coming up and the dotted line, so they agree with the forecast.
// Each sits in its latest payment's category, as the API derives it (T-24-2).
const SCHEDULED_BILLS: SampleScheduledBill[] = [
  { id: 'sc-Netflix', label: 'Netflix', amount: 12.99, nextIn: 20 },
  { id: 'sc-Spotify', label: 'Spotify', amount: 11.99, nextIn: 18 },
].map((b) => ({ ...b, category: L.find((tx) => tx.description === b.label && tx.is_commitment)?.category ?? null }))

function forecastTimeline(horizon = '30') {
  // The horizon control must actually move the chart: build a timeline whose
  // length matches the requested window, with the monthly income/bills cycle
  // repeated so a 1-year view looks like a year, not a stretched month.
  const paydayIn = 24 // matches next_payday = nowPlus(24)
  const days = horizon === 'payday' ? paydayIn : Math.max(1, Math.min(Number(horizon) || 30, 365))
  const start = AVAILABLE_CASH
  const timeline: { date: string; balance: number; events: { label: string; amount: number; kind: string; projected?: boolean }[] }[] = []
  let bal = start
  let min = start
  let minDate = isoDate(new Date())
  for (let i = 0; i <= days; i++) {
    const dom = i % 30 // repeating monthly cycle
    const events: { label: string; amount: number; kind: string; projected?: boolean }[] = []
    if (i > 0 && dom === CONTRIBUTION.nextIn) { bal -= CONTRIBUTION.amount; events.push({ label: CONTRIBUTION.label, amount: -CONTRIBUTION.amount, kind: 'commitment' }) }
    for (const r of cardRepaymentsDue()) {
      if (i === r.due_in) { bal -= r.amount; events.push({ label: r.label, amount: -r.amount, kind: 'repayment', projected: r.projected }) }
    }
    if (i > 0 && dom === 15) { bal -= 1100; events.push({ label: 'Rent', amount: -1100, kind: 'commitment' }) }
    for (const b of SCHEDULED_BILLS) {
      if (i > 0 && dom === b.nextIn) { bal -= b.amount; events.push({ label: b.label, amount: -b.amount, kind: 'commitment' }) }
    }
    if (i > 0 && dom === 24) { bal += 3200; events.push({ label: 'Salary', amount: 3200, kind: 'income' }) }
    if (i > 0 && dom === MORTGAGE_BILL.nextIn) { bal -= MORTGAGE_BILL.amount; events.push({ label: MORTGAGE_BILL.label, amount: -MORTGAGE_BILL.amount, kind: 'commitment' }) }
    bal = Math.round(bal * 100) / 100
    const date = isoDate(nowPlus(i))
    // Every event carries `projected`, as the API sends it (T-12-7a).
    timeline.push({ date, balance: bal, events: events.map((e) => ({ projected: false, ...e })) })
    if (bal < min) { min = bal; minDate = date }
  }
  return {
    horizon, horizon_end: isoDate(nowPlus(days)), start_balance: start,
    end_balance: bal, min_balance: min, min_date: minDate, overdraft_limit: 500,
    breaches: [], timeline,
  }
}

// The forecast with its budget line (T-11-10): the sample budgets by the API's rule.
function forecastResponse(horizon = '30') {
  const forecast = forecastTimeline(horizon)
  const list = sampleBudgetList(BUDGET_LEDGER, PAYDAY_AGO, false, SAMPLE_PAID_BACK, SCHEDULED_BILLS)
  const reach = forecast.timeline.find((t) => t.date === list.cycle.end)
    ?? forecastTimeline('payday').timeline.find((t) => t.date === list.cycle.end)
  const { projection, reason } = sampleBudgetProjection(list, forecast.timeline, reach ? reach.balance : forecast.end_balance,
    SCHEDULED_BILLS)
  const gross = sampleBudgetList(GROSS_BUDGET_LEDGER, PAYDAY_AGO, false, [], SCHEDULED_BILLS)
  const raised = Number(list.summary_this_cycle.left) - Number(gross.summary_this_cycle.left)
  return {
    ...forecast,
    budget_projection: projection && { ...projection, left_raised_by_marks: raised.toFixed(2) },
    budget_projection_reason: reason,
  }
}

function trendResponse(months: number) {
  const base = [980, 1120, 1040, 1210, 1005, 1180]
  const out = []
  const now = new Date()
  for (let i = months - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const total = base[(base.length - 1 - i + base.length * 2) % base.length]
    out.push({
      month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      total: String(total), charged_to_credit: String(Math.round(total * 0.4)),
      paid_from_cash: String(Math.round(total * 0.6)),
    })
  }
  return { months: out }
}

function commitmentsResponse() {
  const mk = (
    label: string, amount: number, direction: string, nextIn: number,
    cadence = 'monthly', isPayday = false,
  ) => ({
    id: `sc-${label}`, direction, label, amount, cadence, interval_days: null,
    interval_months: cadence === 'every_n_months' ? 12 : null, next_date: isoDate(nowPlus(nextIn)),
    source: 'detected', status: 'confirmed', account_id: null, match_key: `${direction}:${label.toLowerCase()}`,
    is_payday: isPayday,
  })
  return [
    // Two income streams so the payday picker has something to disambiguate;
    // the salary is the designated payday.
    mk('Salary', 3200, 'income', 24, 'monthly', true),
    mk('Freelance', 480, 'income', 11),
    mk('Rent', 1100, 'expense', 25),
    mk('Gym', 32, 'expense', 26),
    mk('Phone', 20, 'expense', 12),
    mk('Netflix', 12.99, 'expense', 20),
    mk('Spotify', 11.99, 'expense', 18),
    // The ISA's contribution: a linked bill, edited through the holding.
    { ...mk(CONTRIBUTION.label, CONTRIBUTION.amount, 'expense', CONTRIBUTION.nextIn), id: CONTRIBUTION.id,
      source: 'manual', account_id: CONTRIBUTION.account, linked_holding: true },
    // The mortgage's payment: follows the mortgage (T-12-7b).
    { ...mk(MORTGAGE_BILL.label, MORTGAGE_BILL.amount, 'expense', MORTGAGE_BILL.nextIn), id: MORTGAGE_BILL.id,
      source: 'manual', account_id: 'sa1', linked_liability: true, linked_mortgage: true },
  ]
}

function netWorthHistory(months: number, includeInvestments = true) {
  const out = []
  const now = new Date()
  const r2 = (n: number) => Math.round(n * 100) / 100
  for (let i = months; i >= 0; i--) {
    const d = i === 0 ? now : new Date(now.getFullYear(), now.getMonth() - i + 1, 0)
    const nw = r2(NET_WORTH - i * 520 - (i % 2) * 140)
    const assets = r2(ASSETS_TOTAL - i * 300)
    const bank = r2(nw - assets + LIABILITIES_TOTAL)
    // The house is property at one value; the rest are investments. The
    // groups add up to net worth (cash + investments + property - debt), as
    // the API's (T-11-6a).
    const investments = r2(assets - PROPERTY_TOTAL)
    const shownAssets = includeInvestments ? assets : r2(assets - investments)
    out.push({
      date: isoDate(d), bank: String(bank), assets: String(shownAssets), liabilities: String(LIABILITIES_TOTAL),
      net_worth: String(r2(bank + shownAssets - LIABILITIES_TOTAL)),
      cash: String(r2(bank + CREDIT_OWED)), investments: String(investments), property: PROPERTY_TOTAL.toFixed(2),
      debt: String(r2(CREDIT_OWED + LIABILITIES_TOTAL)),
    })
  }
  return out
}

// Coherent with netWorthHistory: the sample climbs ~£520/mo, so each horizon
// reads as "up" and the % is against the reconstructed starting point.
function positionResponse() {
  const now = new Date()
  const horizons: [string, string, number | null][] = [
    ['1m', '1 month', 1], ['3m', '3 months', 3], ['6m', '6 months', 6], ['1y', '1 year', 12], ['all', 'All time', 22],
  ]
  const since = new Date(now.getFullYear(), now.getMonth() - 22, now.getDate())
  return {
    as_of: isoDate(now),
    net_worth: String(NET_WORTH),
    bank: String(Math.round((NET_WORTH - ASSETS_TOTAL + LIABILITIES_TOTAL) * 100) / 100),
    assets: String(ASSETS_TOTAL),
    liabilities: String(LIABILITIES_TOTAL),
    since: isoDate(since),
    changes: horizons.map(([key, label, months]) => {
      const m = months ?? 22
      const from = new Date(now.getFullYear(), now.getMonth() - m, now.getDate())
      const fromValue = Math.round((NET_WORTH - m * 520 - (m % 2) * 140) * 100) / 100
      const change = Math.round((NET_WORTH - fromValue) * 100) / 100
      return {
        key, label, from_date: isoDate(from), available: true,
        from_value: String(fromValue), change: String(change),
        change_pct: fromValue > 0 ? (Math.round((change / fromValue) * 1000) / 10).toFixed(1) : null,
      }
    }),
  }
}

function decompositionResponse(months: number) {
  // Coherent with netWorthHistory: assets climb ~£300/mo in the sample. Say
  // two-thirds of the move was contributions, the rest growth.
  const delta = Math.min(months, 12) * 300
  const contributions = Math.round(delta * (2 / 3))
  const start = new Date()
  start.setMonth(start.getMonth() - months)
  return {
    start_date: isoDate(start),
    end_date: isoDate(new Date()),
    assets_start: String(ASSETS_TOTAL - delta),
    assets_end: String(ASSETS_TOTAL),
    assets_delta: String(delta),
    contributions: String(contributions),
    growth: String(delta - contributions),
    flows_recorded: 4,
  }
}

function nudgesResponse() {
  // One ranked feed, as the API sorts it (stable for equal ranks).
  return [...cardOverlapNudges(), ...cashDragNudges(), ...sampleBudgetNudges(sampleBudgetList(BUDGET_LEDGER, PAYDAY_AGO, false, SAMPLE_PAID_BACK, SCHEDULED_BILLS))]
    .sort((a, b) => a.rank - b.rank)
}

// T-12-7a (ux demo): a manual "Card bill" ticked as a card payment, due
// before payday like the Harbor Rewards bill. It is smaller, so by the API's
// rule (the larger counts once) the forecast and safe-to-spend keep the
// projected bill and leave this item out: no figure moves.
const SAMPLE_PAYDAY_IN = 24 // next_payday = nowPlus(24)
const SAMPLE_CARD_BILL = { id: 'sp2', name: 'Card bill', amount: 400, dueIn: 6 }

function plannedItemsResponse() {
  return [
    { id: 'sp1', name: 'New laptop', direction: 'expense', kind: 'installment_plan', start_date: isoDate(nowPlus(13)), amount: null, total_amount: 1200, installments: 6, is_card_payment: false, card_payment_overlap: false },
    { id: SAMPLE_CARD_BILL.id, name: SAMPLE_CARD_BILL.name, direction: 'expense', kind: 'one_off', start_date: isoDate(nowPlus(SAMPLE_CARD_BILL.dueIn)), amount: SAMPLE_CARD_BILL.amount, total_amount: null, installments: null, cadence: null, interval_days: null, interval_months: null, end_date: null, apr: null, fee_amount: null, active: true, is_card_payment: true, card_payment_overlap: true },
  ]
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const dayMonth = (d: Date) => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
const money2 = (n: number) => `£${n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

/** The API's overlap nudge (nudges._card_payment_overlap) for the sample's
 *  first pay window: today to the day before payday. */
function cardOverlapNudges() {
  const manual = SAMPLE_CARD_BILL.amount
  // The card repayments due in the window (today to the day before payday),
  // as the API's overlap reads them.
  const projected = cardRepaymentsDue().filter((r) => r.due_in < SAMPLE_PAYDAY_IN).reduce((t, r) => t + r.amount, 0)
  const larger = Math.max(manual, projected)
  const end = nowPlus(SAMPLE_PAYDAY_IN - 1)
  return [{
    id: `card_payment_overlap_${isoDate(end)}`,
    rank: 0,
    body: `Your planned card payments (${money2(manual)}) overlap your projected card bills (${money2(projected)}). nilu counts the larger, ${money2(larger)}, once.`,
    detail: `Between ${dayMonth(nowPlus(0))} and ${dayMonth(end)}. Planned items you marked as a card payment and the card repayments nilu projects pay the same cards, so only the larger total counts in safe to spend and the forecast.`,
    source: null,
    as_of: null,
  }]
}

function cashDragNudges() {
  // Mirrors the backend cash-drag arithmetic for the sample's £12,000 saver
  // at the curated 4.5% benchmark (see api reference/uk_reference.py).
  const potential = Math.round(SAVINGS_TOTAL * 0.045)
  return [
    {
      id: 'cash_drag',
      rank: 1,
      body: `£${SAVINGS_TOTAL.toLocaleString('en-GB')} sits in savings accounts. If it's earning little or nothing, that's roughly £${potential.toLocaleString('en-GB')}/yr of interest at the best easy-access rate (4.5% as of 1 Jul 2026).`,
      detail: `£${SAVINGS_TOTAL.toLocaleString('en-GB')} × 4.5% = £${potential.toLocaleString('en-GB')}/yr. We can't see your actual rate, so this compares against 0% — your real gap may be smaller. Benchmark: public best-buy tables (curated snapshot).`,
      source: 'public best-buy tables (curated snapshot)',
      as_of: '2026-07-01',
    },
  ]
}

// Mirrors the backend projection: compound monthly growth + contributions from
// today's net worth. An estimate, not advice — same numbers as the real API.
function projectionResponse(q: Record<string, any>) {
  const target = q.target_amount != null ? Number(q.target_amount) : null
  // No custom contribution -> derive from the sample's cashflow, mirroring the
  // backend: income commitments − bills − average everyday spending.
  const round2 = (n: number) => Math.round(n * 100) / 100
  const INCOME_MONTHLY = 3200 + 480 // salary + freelance
  // Every confirmed monthly bill, as the API sums them: the ISA contribution
  // (counted once; the holding takes it) and the mortgage payment included.
  const BILLS_MONTHLY = commitmentsResponse()
    .filter((c) => c.direction === 'expense' && c.status === 'confirmed' && c.cadence === 'monthly')
    .reduce((t, c) => t + c.amount, 0)
  const AVG_SPENDING = round2((980 + 1120 + 1040 + 1210 + 1005 + 1180) / 6)
  const derived = q.monthly_contribution == null
  // Spending is always subtracted (owner, T-12-0), as the API: "none" and an
  // old subtract_spending=false read as budgets. A custom monthly_spending
  // replaces the measured average under Average; "budgets" uses the sample
  // budgets' total (T-11-8), as the API uses the active, unpaused limits.
  const legacyNoSpending = q.spending_source == null && String(q.subtract_spending ?? 'true') === 'false'
  const source: string | null = q.spending_source === 'none' || legacyNoSpending ? 'budgets' : q.spending_source ?? null
  const subtractSpending = true
  const customSpend = q.monthly_spending != null && source !== 'budgets' ? Math.max(0, Number(q.monthly_spending)) : null
  const useBudgets = source === 'budgets'
  const spendLeg = useBudgets ? SAMPLE_BUDGETS_MONTHLY : customSpend != null ? customSpend : AVG_SPENDING
  const spendingUsed = !source ? null : useBudgets ? 'budgets' : customSpend != null ? 'estimate' : 'average'
  // Unlinked (legacy) contributions move cash into their holdings (T-12-0);
  // the sample's only contribution is linked, so a bill above.
  const UNLINKED = ASSETS.filter((a) => !a.linked).reduce((s, a) => s + a.monthly, 0)
  const basis = derived
    ? {
        income_monthly: String(round2(INCOME_MONTHLY)),
        bills_monthly: String(round2(BILLS_MONTHLY)),
        avg_spending_monthly: String(AVG_SPENDING),
        contribution: String(round2(INCOME_MONTHLY - BILLS_MONTHLY - spendLeg - UNLINKED)),
        contributions_monthly: UNLINKED.toFixed(2),
        spending_months_sampled: 6,
        spending_subtracted: subtractSpending,
        spending_applied: String(round2(spendLeg)),
        spending_source: subtractSpending && customSpend != null ? 'custom' : 'measured',
        spending_choice: source,
        spending_used: spendingUsed,
        budgets_monthly: source ? SAMPLE_BUDGETS_MONTHLY.toFixed(2) : null,
        budgets_fallback: source ? false : null,
        sampled_months: [980, 1120, 1040, 1210, 1005, 1180].map((total, i) => {
          const d = new Date()
          d.setMonth(d.getMonth() - (6 - i))
          return { month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`, total: String(total) }
        }),
      }
    : null
  const monthly = derived ? round2(INCOME_MONTHLY - BILLS_MONTHLY - spendLeg - UNLINKED) : (Number(q.monthly_contribution) || 0) - UNLINKED
  const growth = Math.min(50, Math.max(-50, Number(q.annual_growth_pct) || 0)) / 100
  const r = Math.pow(1 + growth, 1 / 12) - 1
  const addM = (m: number) => {
    const d = new Date()
    d.setMonth(d.getMonth() + m)
    return isoDate(d)
  }
  const round = (n: number) => Math.round(n * 100) / 100
  // Component model, mirroring the backend: bank cash held flat, surplus swept
  // into investments at the growth rate, each asset at its own assumed rate
  // (liabilities flat by default).
  const BANK = AVAILABLE_CASH + SAVINGS_TOTAL - CREDIT_OWED
  // Each holding at its own rate with the engine's arithmetic (T-11-4);
  // include_investments=false leaves the investments out (T-11-4c).
  const includeInvestments = String(q.include_investments ?? 'true') !== 'false'
  const components = ASSETS.filter((a) => includeInvestments || !isInvestmentAsset(a)).map((a) => ({
    name: a.name,
    value: a.value,
    growth_pct: a.growth,
    rate: Math.pow(1 + a.growth / 100, 1 / 12) - 1,
    contribution: a.monthly,
    isLiability: a.value < 0,
  }))
  const netWorthNow = includeInvestments ? NET_WORTH : NET_WORTH - INVESTMENTS_TOTAL
  const assetsAt0 = components.reduce((s, c) => s + c.value, 0)
  // Liabilities kept flat in the sample projection (as the API does for an
  // unlinked one), as their own component.
  const owed = String(round(LIABILITIES_TOTAL))
  const timeline: { date: string; value: string; cash: string; invested: string; assets: string; liabilities: string }[] = [
    { date: addM(0), value: String(round(netWorthNow)), cash: String(round(BANK)), invested: '0.00', assets: String(round(assetsAt0)), liabilities: owed },
  ]
  // Surplus waterfall (mirrors backend): positive months invest; negative
  // months drain cash first, then investments; shortfall never compounds.
  let cash = BANK
  let invested = 0
  // Already there today — mirror the backend's day-0 check.
  let target_date: string | null = target != null && netWorthNow >= target ? addM(0) : null
  let monthsWanted = target_date ? 6 : 120
  for (let m = 1; m <= 600; m++) {
    invested *= 1 + r
    if (monthly >= 0) invested += monthly
    else {
      cash += monthly
      if (cash < 0) {
        invested += cash
        cash = 0
        if (invested < 0) {
          cash = invested
          invested = 0
        }
      }
    }
    let assetsValue = 0
    for (const c of components) {
      c.value = c.value * (1 + c.rate) + c.contribution
      if (c.isLiability && c.value > 0) c.value = 0 // paid off — stop at zero
      assetsValue += c.value
    }
    const value = cash + invested + assetsValue - LIABILITIES_TOTAL
    if (target != null && !target_date && value >= target) {
      target_date = addM(m)
      monthsWanted = Math.min(600, m + 6)
    }
    // Every month is kept while the target is still being searched for and
    // trimmed after, as the API does, so the line never skips month 121 on.
    timeline.push({
      date: addM(m),
      value: String(round(value)),
      cash: String(round(cash)),
      invested: String(round(invested)),
      assets: String(round(assetsValue)),
      liabilities: owed,
    })
    if (m >= monthsWanted && (target == null || target_date)) break
  }
  timeline.splice(monthsWanted + 1)
  return {
    current_net_worth: String(round(netWorthNow)),
    target_amount: target != null ? String(target) : null,
    target_date,
    // Custom: the typed figure, as the API echoes it (the whole monthly change).
    monthly_contribution: String(round(derived ? monthly : Number(q.monthly_contribution) || 0)),
    contribution_basis: basis,
    annual_growth_pct: String(Number(q.annual_growth_pct) || 0),
    mode: derived ? 'cashflow' : 'custom',
    bank_component: String(round(BANK)),
    asset_assumptions: components.map((c) => ({
      name: c.name,
      growth_pct: String(c.growth_pct),
      monthly_contribution: String(c.contribution),
    })),
    as_of: addM(0),
    timeline,
  }
}

function liabilitiesResponse() {
  const asOf = isoDate(nowMinus(20))
  return LIABILITIES.map((l) => ({
    id: l.id, kind: l.kind, lender: l.lender, balance: l.balance, balance_as_of: asOf, apr: l.apr,
    payment: l.payment, cadence: l.cadence, start_date: isoDate(nowMinus(400)), end_date: l.end_date,
    opted_out: false, current_balance: l.balance, next_payment_date: isoDate(nowPlus(10)),
    payments_remaining: l.payments_remaining, payoff_date: isoDate(nowPlus(l.payoff_days)),
    interest_remaining: l.interest_remaining,
    total_cost: (Number(l.balance) + Number(l.interest_remaining)).toFixed(2),
    paid_off: false, balance_stale: false, link_result: null,
    ...(l.kind === 'mortgage'
      ? { property_asset_id: MORTGAGE_PROPERTY, linked_commitment: { id: MORTGAGE_BILL.id, label: MORTGAGE_BILL.label } }
      : { property_asset_id: null, linked_commitment: null }),
  }))
}

function assetsResponse() {
  return ASSETS.map((a) => ({
    id: a.id, name: a.name, asset_type: a.asset_type,
    assumed_growth_pct: String(a.growth),
    // Linked: the bill carries the contribution, never the asset as well.
    monthly_contribution: a.monthly && !a.linked ? String(a.monthly) : null,
    linked_commitment: a.linked
      ? { id: CONTRIBUTION.id, label: CONTRIBUTION.label, amount: CONTRIBUTION.amount.toFixed(2), next_date: isoDate(nowPlus(CONTRIBUTION.nextIn)), pay_from_account_id: CONTRIBUTION.account, created: true }
      : null,
    valuations: assetValuations(a).map((v) => ({ id: v.id, value: String(v.value), valued_at: v.date })),
    value_today: a.value.toFixed(2),
    // The API's equity line (T-12-6b): value today minus its mortgages.
    ...equityOf(a),
  }))
}

function equityOf(a: (typeof ASSETS)[number]) {
  if (a.id !== MORTGAGE_PROPERTY) return { mortgage_owed: null, equity: null }
  const owed = LIABILITIES.filter((l) => l.kind === 'mortgage').reduce((t, l) => t + Number(l.balance), 0)
  return { mortgage_owed: owed.toFixed(2), equity: (a.value - owed).toFixed(2) }
}

function holdingsProjectionResponse(q: Record<string, any>) {
  const months = Math.max(1, Math.min(600, Number(q.months) || 120))
  const holdings = ASSETS.filter(isInvestmentAsset).map((a) => ({
    id: a.id, name: a.name, asset_type: a.asset_type, value: a.value, growth: a.growth, monthly: a.monthly,
    valuations: assetValuations(a).map(({ date, value }) => ({ date, value })),
  }))
  const monthDate = (m: number) => {
    const d = new Date()
    d.setMonth(d.getMonth() + m)
    return isoDate(d)
  }
  return sampleInvestmentGraph(holdings, months, q.holding_id ? String(q.holding_id) : null, monthDate, isoDate(new Date()))
}

function statusResponse() {
  return {
    is_connected: true, connections_count: 3,
    last_synced_at: new Date(Date.now() - 26 * 60000).toISOString(),
    connections: [
      { id: 'sc1', provider_name: 'Everly Bank', is_expired: false, expires_at: null },
      { id: 'sc2', provider_name: 'Acorn Bank', is_expired: false, expires_at: null },
      { id: 'sc3', provider_name: 'Harbor Financial', is_expired: false, expires_at: null },
    ],
    message: 'ok',
  }
}

// Budget freshness (T-12-11): every sample bank synced with the status above.
function syncStatusResponse() {
  const s = statusResponse()
  return {
    connections: s.connections.map((c) => ({
      connection_id: c.id, provider: c.provider_name, last_synced_at: s.last_synced_at, consent: 'active', stale: false,
    })),
  }
}

// A shared pack's preview (T-12-11): a small sample pack, never a real one.
function sharedPackResponse() {
  const rules = [
    { pattern: 'FERNWOOD', match_type: 'contains', category: 'Groceries' },
    { pattern: 'SOLENT TRANSIT', match_type: 'contains', category: 'Transport' },
    { pattern: 'COBALT COFFEE', match_type: 'contains', category: 'Eating out' },
  ]
  return { name: 'Sample everyday pack', description: 'Shared in demo mode', rule_count: rules.length, rules, already_owned: false }
}

// --- param normalisation + dispatch ---------------------------------------- #

function readParams(params: unknown): TxQuery & Record<string, any> {
  const out: Record<string, any> = {}
  const set = (k: string, v: string) => {
    if (k === 'category') (out.category ??= []).push(v)
    else if (['page', 'page_size', 'min_amount', 'max_amount'].includes(k)) out[k] = Number(v)
    else if (['include_excluded', 'exclude_commitments', 'hide_transfers', 'hide_card_payments'].includes(k)) out[k] = v === 'true'
    else out[k] = v
  }
  if (params instanceof URLSearchParams) params.forEach((v, k) => set(k, v))
  else if (params && typeof params === 'object') {
    for (const [k, v] of Object.entries(params as Record<string, unknown>)) {
      if (Array.isArray(v)) v.forEach((x) => set(k, String(x)))
      else if (v != null) set(k, String(v))
    }
  }
  return out as TxQuery
}

/** The sample response for a GET endpoint, or {} for anything unmatched. */
/** The sample card's statement. It reconciles with the summary: £550.30 of
 *  the £640.30 owed was billed and is due on the day of the first repayment;
 *  the £90.00 spent since is the projected second one (T-12-7a). Other
 *  accounts have no statement. */
const SAMPLE_STATEMENT_DUE = () => isoDate(nowPlus(STATEMENT_DUE_IN))

/** The sample card's statement as the summary carries it. */
function sampleStatement() {
  return { statement_balance: STATEMENT_OWED.toFixed(2), due_date: SAMPLE_STATEMENT_DUE(), paid: false, missing: false }
}

function statementsResponse(path: string) {
  const empty = { statements: [], current: null, missing_statement: false, conflict: false, next_payment: null }
  if (!path.includes('/accounts/sa4/')) return empty
  const owed = STATEMENT_OWED.toFixed(2)
  const statement = {
    id: 'ss1', account_id: 'sa4', statement_balance: owed, statement_date: isoDate(nowMinus(22)),
    due_date: SAMPLE_STATEMENT_DUE(), minimum_due: '25.00', source: 'manual' as const,
  }
  return {
    statements: [statement],
    current: {
      statement_id: 'ss1', source: 'manual', statement_balance: owed, statement_date: statement.statement_date,
      due_date: statement.due_date, minimum_due: '25.00', payments_since_statement: '0.00',
      amount_still_due: owed, unbilled: SPENT_SINCE.toFixed(2), paid: false,
    },
    missing_statement: false,
    conflict: false,
    next_payment: { amount: owed, date: statement.due_date, from_account_name: 'Everly Current' },
  }
}

/** GET /plan (T-24-6), by the API's rules (services/plan.py) from the
 *  sample's own commitments, ledger, card repayments, planned items and
 *  budgets. A commitment's category is its latest payment's. Paid: a
 *  payment this cycle. Due: its next date by the eve, or due earlier this
 *  cycle and not paid. In an unpaused budget's category (and not £0 or
 *  linked) it sits under that budget; otherwise in Fixed. Card repayments
 *  are the ones the demo forecast schedules; a card-flagged planned item
 *  counts only where it is larger than them (safe to spend's rule). */
function planResponse() {
  type Status = 'paid' | 'due' | 'not_due_this_cycle'
  type Item = { source: 'commitment' | 'card_repayment' | 'planned'; commitment_id: string | null; label: string;
    due_date: string | null; amount: string; status: Status; transaction_id: string | null }
  const list = sampleBudgetList(BUDGET_LEDGER, PAYDAY_AGO, false, SAMPLE_PAID_BACK)
  const eveIn = list.cycle.days_left
  const r2 = (n: number) => (Math.round(n * 100) / 100).toFixed(2)
  const sum = (xs: { amount: string }[]) => xs.reduce((t, x) => t + Number(x.amount), 0)
  const daysTo = (iso: string) => Math.round((Date.parse(iso) - Date.parse(isoDate(new Date()))) / 86400000)
  const payments = (label: string) => L.filter((tx) => tx.description === label && tx.is_commitment)
  const budgets = list.budgets.filter((b) => !b.paused)
  const budgeted = new Set(budgets.map((b) => b.category))
  const all = commitmentsResponse()

  const income = all.filter((c) => c.direction === 'income').map((c) => {
    const paid = payments(c.label).find((tx) => tx.daysAgo <= PAYDAY_AGO)
    return paid
      ? { id: c.id, label: c.label, date: isoDate(nowMinus(paid.daysAgo)), amount: r2(paid.amount), status: 'received' as const, transaction_id: paid.id }
      : { id: c.id, label: c.label, date: c.next_date, amount: r2(c.amount), status: 'expected' as const, transaction_id: null }
  }).filter((i) => i.status === 'received' || daysTo(i.date) <= eveIn)

  const groups = new Map<string, Item[]>()
  const add = (source: Item['source'], category: string | null, item: Omit<Item, 'source'>) => {
    const key = JSON.stringify([source, category])
    groups.set(key, [...(groups.get(key) ?? []), { source, ...item }])
  }
  const inBudget = new Map<string, { commitment_id: string; label: string; date: string; amount: string; status: 'paid' | 'due'; transaction_id: string | null }[]>()
  for (const c of all.filter((x) => x.direction === 'expense')) {
    const paid = payments(c.label).filter((tx) => tx.daysAgo <= PAYDAY_AGO)
    const category = payments(c.label)[0]?.category ?? null
    const budget = category !== null && budgeted.has(category) && c.amount > 0 && !('linked_holding' in c) && !('linked_liability' in c)
    const nextIn = daysTo(c.next_date)
    const due = [nextIn - 30].filter((d) => d >= -PAYDAY_AGO && d <= 0).slice(paid.length)  // due earlier, unpaid
      .concat(nextIn > 0 && nextIn <= eveIn ? [nextIn] : [])
    const lines = [
      ...paid.map((tx) => ({ date: isoDate(nowMinus(tx.daysAgo)), amount: r2(tx.amount), status: 'paid' as const, transaction_id: tx.id })),
      ...due.map((d) => ({ date: isoDate(nowPlus(d)), amount: r2(c.amount), status: 'due' as const, transaction_id: null })),
    ]
    if (budget && category) {
      inBudget.set(category, [...(inBudget.get(category) ?? []), ...lines.map((l) => ({ commitment_id: c.id, label: c.label, ...l }))])
    } else if (lines.length) {
      for (const l of lines) add('commitment', category, { commitment_id: c.id, label: c.label, due_date: l.date, amount: l.amount, status: l.status, transaction_id: l.transaction_id })
    } else {
      add('commitment', category, { commitment_id: c.id, label: c.label, due_date: null, amount: r2(c.amount), status: 'not_due_this_cycle', transaction_id: null })
    }
  }
  const repayments = cardRepaymentsDue().filter((r) => r.due_in > 0 && r.due_in <= eveIn)
  const planned = [
    { label: 'New laptop', dueIn: 13, amount: 1200 / 6, card: false },
    { label: SAMPLE_CARD_BILL.name, dueIn: SAMPLE_CARD_BILL.dueIn, amount: SAMPLE_CARD_BILL.amount, card: true },
  ].filter((x) => x.dueIn > 0 && x.dueIn <= eveIn)
  const cardPlanned = planned.filter((x) => x.card).reduce((t, x) => t + x.amount, 0)
  const keepRepayments = repayments.reduce((t, r) => t + r.amount, 0) >= cardPlanned
  if (keepRepayments) repayments.forEach((r) => add('card_repayment', null, { commitment_id: null, label: r.label, due_date: isoDate(nowPlus(r.due_in)), amount: r2(r.amount), status: 'due', transaction_id: null }))
  planned.filter((x) => !x.card || !keepRepayments).forEach((x) => add('planned', null, { commitment_id: null, label: x.label, due_date: isoDate(nowPlus(x.dueIn)), amount: r2(x.amount), status: 'due', transaction_id: null }))

  const fixedGroups = [...groups].map(([key, items]) => {
    const [source, category] = JSON.parse(key) as [Item['source'], string | null]
    const counted = items.filter((i) => i.status !== 'not_due_this_cycle')
    return { source, category, total: r2(sum(counted)), items, paid_count: items.filter((i) => i.status === 'paid').length, count: counted.length }
  })
  const fixedItems = fixedGroups.flatMap((g) => g.items.filter((i) => i.status !== 'not_due_this_cycle'))
  const planBudgets = budgets.map((b) => {
    const commitments = inBudget.get(b.category) ?? []
    const coming = sum(commitments.filter((c) => c.status === 'due'))
    return {
      budget_id: b.id, category: b.category, limit: r2(b.limit_pounds), spent: b.spent, coming_up: r2(coming),
      status: b.status, over_by: b.over_by, commitments, commitment_count: commitments.length,
      other_purchases: r2(Math.max(0, Number(b.spent) - sum(commitments.filter((c) => c.status === 'paid')))),
    }
  })
  const incomeTotal = sum(income)
  const fixedTotal = sum(fixedItems)
  const plannedTotal = planBudgets.reduce((t, b) => t + Math.max(Number(b.limit), Number(b.spent) + Number(b.coming_up)), 0)
  const notPlanned = incomeTotal - fixedTotal - plannedTotal
  return {
    cycle: { start: list.cycle.start, end: list.cycle.end, days_left: list.cycle.days_left },
    income: {
      total: r2(incomeTotal), items: income,
      received_count: income.filter((i) => i.status === 'received').length,
      expected_count: income.filter((i) => i.status === 'expected').length,
    },
    fixed: {
      total: r2(fixedTotal), paid: r2(sum(fixedItems.filter((i) => i.status === 'paid'))),
      to_pay: r2(sum(fixedItems.filter((i) => i.status === 'due'))),
      paid_count: fixedItems.filter((i) => i.status === 'paid').length, count: fixedItems.length, groups: fixedGroups,
    },
    budgets: {
      limits_total: r2(planBudgets.reduce((t, b) => t + Number(b.limit), 0)), planned_total: r2(plannedTotal),
      spent: r2(planBudgets.reduce((t, b) => t + Number(b.spent), 0)),
      coming_up: r2(planBudgets.reduce((t, b) => t + Number(b.coming_up), 0)), count: planBudgets.length, items: planBudgets,
    },
    spent_outside_budgets: list.other_spending,
    not_planned: r2(notPlanned),
    outside_vs_not_planned: r2(Number(list.other_spending) - notPlanned),
  }
}

export function sampleResponse(url: string, params: unknown): unknown {
  const [path, queryString] = url.split('?')
  const p = readParams(params)
  // Some calls embed params directly in the URL (e.g. net-worth-history's
  // ?months=) instead of axios `params`; merge those in so a filter is honoured
  // however it was passed — otherwise the sample silently ignores it.
  if (queryString) {
    const fromUrl = readParams(new URLSearchParams(queryString)) as Record<string, unknown>
    for (const [k, v] of Object.entries(fromUrl)) {
      if ((p as Record<string, unknown>)[k] === undefined) (p as Record<string, unknown>)[k] = v
    }
  }
  const is = (suffix: string) => path.endsWith(suffix)

  if (is('/auth/me')) return { id: 'sample-user', email: 'you@sample.example' }
  if (is('/banking/status')) return statusResponse()
  if (is('/banking/sync-status')) return syncStatusResponse()
  if (/\/analytics\/accounts\/[^/]+\/repayments$/.test(path)) return []
  if (path.includes('/rules/shared/')) return sharedPackResponse()
  if (is('/banking/accounts')) return ACCOUNTS.map(({ id, display_name, provider_name, account_type }) => ({ id, display_name, provider_name, account_type }))
  if (is('/banking/transactions/facets')) return {
    categories: [...new Set(L.map((x) => x.category))].sort(),
    merchants: [...new Set(L.map((x) => x.merchant_name))].sort(),
  }
  if (path.includes('/banking/transactions')) return txResponse(p)
  if (is('/analytics/summary')) return summaryResponse()
  if (path.includes('/analytics/forecast')) return forecastResponse(String(p.horizon ?? '30'))
  if (path.includes('/analytics/spending/trend')) return trendResponse(Number(p.months) || 6)
  if (path.includes('/analytics/spending')) return spendingResponse(p as any)
  if (is('/analytics/commitments')) return commitmentsResponse()
  if (is('/analytics/planned-items')) return plannedItemsResponse()
  if (is('/analytics/nudges')) return nudgesResponse()
  if (path.includes('/analytics/net-worth-decomposition')) return decompositionResponse(Number(p.months) || 12)
  if (path.includes('/analytics/net-worth-projection')) return projectionResponse(p as Record<string, any>)
  if (path.includes('/analytics/net-worth-history')) return netWorthHistory(Number(p.months) || 12, String(p.include_investments ?? 'true') !== 'false')
  if (path.includes('/analytics/net-worth-position')) return positionResponse()
  if (is('/statements')) return statementsResponse(path)
  if (is('/assets')) return assetsResponse()
  if (is('/holdings/projection')) return holdingsProjectionResponse(p as Record<string, any>)
  if (is('/liabilities')) return liabilitiesResponse()
  if (is('/card-plans')) return cardPlansResponse()
  if (is('/plan')) return planResponse()
  if (is('/budgets/history')) return sampleBudgetHistory(BUDGET_LEDGER, PAYDAY_AGO, Number(p.cycles) || 6)
  if (is('/budgets')) return sampleBudgetList(BUDGET_LEDGER, PAYDAY_AGO, p.include === 'categories', SAMPLE_PAID_BACK, SCHEDULED_BILLS)
  if (is('/rules')) return { packs: [], personal: [] }
  if (is('/audit')) return auditResponse()
  return {}
}

// --- coverage ledger -------------------------------------------------------- #
// Every GET in services/api.ts must be served by sampleResponse above or be
// listed in one of these, keyed by its path with ${...} written as ':param'.
// sampleCoverage.test.ts enforces it, so a new read endpoint can't silently
// render empty in demo mode. See docs/features/demo-mode.md.

/** Reads that should NOT get sample data: they start real flows or aren't
 *  data views. */
export const UNSAMPLED_BY_DESIGN: Record<string, string> = {
  '/health': 'Liveness probe, not a data view.',
  '/banking/connect': 'Starts a real TrueLayer connection; nothing to fake.',
  '/banking/connections/:param/reconnect': 'Starts a real TrueLayer re-consent; nothing to fake.',
  '/oauth/authorize/details': 'OAuth consent for an MCP client; an auth flow, not a data view.',
}

/** Reads that SHOULD show sample data but don't yet: each renders empty or
 *  errors in demo mode. Fix one by serving it from sampleResponse and
 *  deleting its line here (the coverage test then insists it stays served). */
export const KNOWN_DEMO_GAPS: Record<string, string> = {}
