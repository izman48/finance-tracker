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
  SAMPLE_BUDGETS_MONTHLY, sampleBudgetHistory, sampleBudgetList, sampleBudgetNudges, sampleBudgetProjection, type BudgetLedgerTx,
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
  // noise, in the recent month — shown, labelled, opt-in to hide
  p('Payment to Harbor Rewards', 'Harbor Financial', 'Transfers', 300, 'debit', 'sa1', 6, { excluded: 'card_payment' })
  p('Transfer to Acorn Saver', 'Acorn Bank', 'Transfers', 500, 'debit', 'sa1', 6, { excluded: 'internal_transfer' })
  p('Transfer from Everly', 'Everly Bank', 'Transfers', 500, 'credit', 'sa3', 6, { excluded: 'internal_transfer' })
  return out
}
const L: SampleTx[] = buildLedger()


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
  category: tx.category, amount: tx.amount, daysAgo: tx.daysAgo,
  kind: tx.excluded_reason === 'internal_transfer' ? 'transfer'
    : tx.excluded_reason === 'card_payment' ? 'card_payoff'
    : !isPurchase(tx) ? 'other'
    : tx.is_commitment ? 'commitment' : 'purchase',
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
  const tally = (tx: SampleTx) => {
    const c = byCat.get(tx.category) ?? { total: 0, count: 0 }
    c.total += tx.amount
    c.count += 1
    byCat.set(tx.category, c)
    byMerch.set(tx.merchant_name, (byMerch.get(tx.merchant_name) ?? 0) + tx.amount)
  }

  let total = 0
  let cash = 0
  let credit = 0
  let composition: Record<string, string> | null = null

  if (lens === 'purchases') {
    for (const tx of L) {
      if (!isPurchase(tx) || !inRange(tx) || !inScope(tx) || (q.exclude_commitments && tx.is_commitment)) continue
      if (kindScope && purchaseKind(tx) !== kindScope) continue
      if (purchaseKind(tx) === 'credit') credit += tx.amount
      else cash += tx.amount
      tally(tx)
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
const ASSETS_TOTAL = ASSETS.reduce((s, a) => s + a.value, 0)
const INVESTMENTS_TOTAL = ASSETS.filter(isInvestmentAsset).reduce((s, a) => s + a.value, 0)
const PROPERTY_TOTAL = ASSETS.filter((a) => a.asset_type === 'property').reduce((s, a) => s + a.value, 0)
const NET_WORTH = AVAILABLE_CASH + SAVINGS_TOTAL + ASSETS_TOTAL - CREDIT_OWED - LIABILITIES_TOTAL

function summaryResponse() {
  // rent + phone + subs + gym, and the ISA contribution (a linked bill).
  const committed = Math.round((1100 + 20 + 12.99 + 11.99 + 32 + CONTRIBUTION.amount) * 100) / 100
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
    next_repayments: [{ account_id: 'sa4', label: 'Harbor Rewards', amount: CREDIT_OWED, due_date: isoDate(nowPlus(8)) }],
    accounts: ACCOUNTS.map((a) => ({
      id: a.id, display_name: a.display_name, provider_name: a.provider_name,
      account_type: a.account_type, role: a.role, current_balance: a.current_balance,
      credit_owed: a.role === 'credit' ? -a.current_balance : null,
      // T-10-14: the sample card's statement, the same bill as next_repayments.
      ...(a.role === 'credit' ? { statement: { statement_balance: String(CREDIT_OWED), due_date: isoDate(nowPlus(8)), paid: false, missing: false } } : {}),
      overdraft_limit: a.overdraft_limit, repayment_cadence: a.role === 'credit' ? 'end_of_month' : null,
      repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null,
      repayment_strategy: a.role === 'credit' ? 'full_balance' : null,
      repayment_fixed_amount: null, repayment_installments: null, pay_from_account_id: null,
      // The card's statement, as statementsResponse has it (T-10-14a).
      ...(a.role === 'credit' ? { statement: sampleStatement() } : {}),
    })),
  }
}

function forecastTimeline(horizon = '30') {
  // The horizon control must actually move the chart: build a timeline whose
  // length matches the requested window, with the monthly income/bills cycle
  // repeated so a 1-year view looks like a year, not a stretched month.
  const paydayIn = 24 // matches next_payday = nowPlus(24)
  const days = horizon === 'payday' ? paydayIn : Math.max(1, Math.min(Number(horizon) || 30, 365))
  const start = AVAILABLE_CASH
  const timeline: { date: string; balance: number; events: { label: string; amount: number; kind: string }[] }[] = []
  let bal = start
  let min = start
  let minDate = isoDate(new Date())
  for (let i = 0; i <= days; i++) {
    const dom = i % 30 // repeating monthly cycle
    const events: { label: string; amount: number; kind: string }[] = []
    if (i > 0 && dom === CONTRIBUTION.nextIn) { bal -= CONTRIBUTION.amount; events.push({ label: CONTRIBUTION.label, amount: -CONTRIBUTION.amount, kind: 'commitment' }) }
    if (i > 0 && dom === 8) { bal -= CREDIT_OWED; events.push({ label: 'Harbor Rewards payment', amount: -CREDIT_OWED, kind: 'repayment' }) }
    if (i > 0 && dom === 15) { bal -= 1100; events.push({ label: 'Rent', amount: -1100, kind: 'commitment' }) }
    if (i > 0 && dom === 24) { bal += 3200; events.push({ label: 'Salary', amount: 3200, kind: 'income' }) }
    if (i > 0 && dom === MORTGAGE_BILL.nextIn) { bal -= MORTGAGE_BILL.amount; events.push({ label: MORTGAGE_BILL.label, amount: -MORTGAGE_BILL.amount, kind: 'commitment' }) }
    bal = Math.round(bal * 100) / 100
    const date = isoDate(nowPlus(i))
    timeline.push({ date, balance: bal, events })
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
  const list = sampleBudgetList(BUDGET_LEDGER, PAYDAY_AGO, false)
  const reach = forecast.timeline.find((t) => t.date === list.cycle.end)
    ?? forecastTimeline('payday').timeline.find((t) => t.date === list.cycle.end)
  const { projection, reason } = sampleBudgetProjection(list, forecast.timeline, reach ? reach.balance : forecast.end_balance)
  return { ...forecast, budget_projection: projection, budget_projection_reason: reason }
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
    mk('Freelance', 480, 'income', 9),
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
  return [...cardOverlapNudges(), ...cashDragNudges(), ...sampleBudgetNudges(sampleBudgetList(BUDGET_LEDGER, PAYDAY_AGO, false))]
}

// T-12-7a (ux demo): a manual "Card bill" ticked as a card payment, due
// before payday like the Harbor Rewards bill. It is smaller, so by the API's
// rule (the larger counts once) the forecast and safe-to-spend keep the
// projected bill and leave this item out: no figure moves.
const SAMPLE_PAYDAY_IN = 24 // next_payday = nowPlus(24)
const SAMPLE_CARD_BILL = { id: 'sp2', name: 'Card bill', amount: 400, dueIn: 6 }

function plannedItemsResponse() {
  return [
    { id: 'sp1', name: 'New laptop', direction: 'expense', kind: 'installment_plan', start_date: isoDate(nowPlus(9)), amount: null, total_amount: 1200, installments: 6, is_card_payment: false, card_payment_overlap: false },
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
  const projected = CREDIT_OWED // the Harbor Rewards bill, due in 8 days
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
/** The sample card's statement. It reconciles with the summary: the whole
 *  £640.30 owed was billed, is due on the same day as next_repayments, and
 *  nothing has been spent since. Other accounts have no statement. */
const SAMPLE_STATEMENT_DUE = () => isoDate(nowPlus(8))

/** The sample card's statement as the summary carries it. */
function sampleStatement() {
  return { statement_balance: CREDIT_OWED.toFixed(2), due_date: SAMPLE_STATEMENT_DUE(), paid: false, missing: false }
}

function statementsResponse(path: string) {
  const empty = { statements: [], current: null, missing_statement: false, conflict: false, next_payment: null }
  if (!path.includes('/accounts/sa4/')) return empty
  const owed = CREDIT_OWED.toFixed(2)
  const statement = {
    id: 'ss1', account_id: 'sa4', statement_balance: owed, statement_date: isoDate(nowMinus(22)),
    due_date: SAMPLE_STATEMENT_DUE(), minimum_due: '25.00', source: 'manual' as const,
  }
  return {
    statements: [statement],
    current: {
      statement_id: 'ss1', source: 'manual', statement_balance: owed, statement_date: statement.statement_date,
      due_date: statement.due_date, minimum_due: '25.00', payments_since_statement: '0.00',
      amount_still_due: owed, unbilled: '0.00', paid: false,
    },
    missing_statement: false,
    conflict: false,
    next_payment: { amount: owed, date: statement.due_date, from_account_name: 'Everly Current' },
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
  if (is('/budgets/history')) return sampleBudgetHistory(BUDGET_LEDGER, PAYDAY_AGO, Number(p.cycles) || 6)
  if (is('/budgets')) return sampleBudgetList(BUDGET_LEDGER, PAYDAY_AGO, p.include === 'categories')
  if (is('/rules')) return { packs: [], personal: [] }
  if (is('/audit')) return { items: [], next_cursor: null }
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
export const KNOWN_DEMO_GAPS: Record<string, string> = {
  '/banking/sync-status': 'Budget freshness line has no connections in demo mode.',
  '/analytics/accounts/:param/repayments': 'Account settings shows no repayment schedule in demo mode.',
  '/rules/shared/:param': 'Previewing a shared rule pack finds nothing in demo mode.',
}
