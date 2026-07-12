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

const ASSETS: {
  id: string; name: string; asset_type: string; value: number; monthly: number
  instrument?: { id: string; symbol: string; name: string; kind: string; currency: string }
  units?: number; unit_price_gbp?: number
}[] = [
  // monthly: planned contribution (paydown on the loan) — demoes the
  // per-asset contribution leg of the unified projection.
  { id: 'sas1', name: 'Meridian S&S ISA', asset_type: 'isa', value: 18500, monthly: 400 },
  { id: 'sas2', name: 'Sterling Pension', asset_type: 'pension', value: 24000, monthly: 0 },
  // A liability: stored as a negative valuation (amount owed), subtracts from net worth.
  { id: 'sas3', name: 'Car loan', asset_type: 'loan', value: -6800, monthly: 0 },
  // A live-priced crypto holding, so anonymise mode demos the "live" chip.
  {
    id: 'sas4', name: 'Bitcoin', asset_type: 'crypto', value: 4200, monthly: 0,
    instrument: { id: 'sinst-btc', symbol: 'BTC', name: 'Bitcoin', kind: 'crypto', currency: 'GBP' },
    units: 0.12, unit_price_gbp: 35000,
  },
]

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
const ASSETS_TOTAL = ASSETS.reduce((s, a) => s + a.value, 0) // ISA + pension − car loan
const NET_WORTH = AVAILABLE_CASH + SAVINGS_TOTAL + ASSETS_TOTAL - CREDIT_OWED

function summaryResponse() {
  const committed = 1100 + 20 + 12.99 + 11.99 + 32 // rent + phone + subs + gym
  return {
    available_cash: AVAILABLE_CASH,
    overdraft_cushion: 500,
    credit_owed: CREDIT_OWED,
    savings_total: SAVINGS_TOTAL,
    assets_total: ASSETS_TOTAL,
    net_worth: NET_WORTH,
    committed_before_payday: committed,
    safe_to_spend: Math.round((AVAILABLE_CASH - committed) * 100) / 100,
    savable: 820,
    next_payday: isoDate(nowPlus(24)),
    next_repayments: [{ account_id: 'sa4', label: 'Harbor Rewards', amount: CREDIT_OWED, due_date: isoDate(nowPlus(8)) }],
    accounts: ACCOUNTS.map((a) => ({
      id: a.id, display_name: a.display_name, provider_name: a.provider_name,
      account_type: a.account_type, role: a.role, current_balance: a.current_balance,
      overdraft_limit: a.overdraft_limit, repayment_cadence: a.role === 'credit' ? 'end_of_month' : null,
      repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null,
      repayment_strategy: a.role === 'credit' ? 'full_balance' : null,
      repayment_fixed_amount: null, repayment_installments: null, pay_from_account_id: null,
    })),
  }
}

function forecastResponse(horizon = '30') {
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
    if (i > 0 && dom === 8) { bal -= CREDIT_OWED; events.push({ label: 'Harbor Rewards payment', amount: -CREDIT_OWED, kind: 'repayment' }) }
    if (i > 0 && dom === 15) { bal -= 1100; events.push({ label: 'Rent', amount: -1100, kind: 'commitment' }) }
    if (i > 0 && dom === 24) { bal += 3200; events.push({ label: 'Salary', amount: 3200, kind: 'income' }) }
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
  ]
}

function netWorthHistory(months: number) {
  const out = []
  const now = new Date()
  for (let i = months; i >= 0; i--) {
    const d = i === 0 ? now : new Date(now.getFullYear(), now.getMonth() - i + 1, 0)
    const nw = Math.round((NET_WORTH - i * 520 - (i % 2) * 140) * 100) / 100
    const assets = Math.round((ASSETS_TOTAL - i * 300) * 100) / 100
    out.push({ date: isoDate(d), bank: String(Math.round((nw - assets) * 100) / 100), assets: String(assets), net_worth: String(nw) })
  }
  return out
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
  const BILLS_MONTHLY = 1100 + 32 + 20 + 12.99 + 11.99
  const AVG_SPENDING = round2((980 + 1120 + 1040 + 1210 + 1005 + 1180) / 6)
  const derived = q.monthly_contribution == null
  // subtract_spending=false: "all my forecasted cashflow lands in my wealth" —
  // the average is shown but not subtracted. A custom monthly_spending
  // replaces the measured average entirely (mirrors the backend).
  const subtractSpending = String(q.subtract_spending ?? 'true') !== 'false'
  const customSpend = q.monthly_spending != null ? Math.max(0, Number(q.monthly_spending)) : null
  const spendLeg = !subtractSpending ? 0 : customSpend != null ? customSpend : AVG_SPENDING
  const basis = derived
    ? {
        income_monthly: String(round2(INCOME_MONTHLY)),
        bills_monthly: String(round2(BILLS_MONTHLY)),
        avg_spending_monthly: String(AVG_SPENDING),
        contribution: String(round2(INCOME_MONTHLY - BILLS_MONTHLY - spendLeg)),
        spending_months_sampled: 6,
        spending_subtracted: subtractSpending,
        spending_applied: String(round2(spendLeg)),
        spending_source: subtractSpending && customSpend != null ? 'custom' : 'measured',
        sampled_months: [980, 1120, 1040, 1210, 1005, 1180].map((total, i) => {
          const d = new Date()
          d.setMonth(d.getMonth() - (6 - i))
          return { month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`, total: String(total) }
        }),
      }
    : null
  const monthly = derived ? round2(INCOME_MONTHLY - BILLS_MONTHLY - spendLeg) : Number(q.monthly_contribution) || 0
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
  const components = ASSETS.map((a) => ({
    name: a.name,
    value: a.value,
    growth_pct: a.value < 0 ? 0 : Number(q.annual_growth_pct) || 0,
    rate: a.value < 0 ? 0 : r,
    contribution: a.monthly,
    isLiability: a.value < 0,
  }))
  const assetsAt0 = components.reduce((s, c) => s + c.value, 0)
  const timeline: { date: string; value: string; cash: string; invested: string; assets: string }[] = [
    { date: addM(0), value: String(round(NET_WORTH)), cash: String(round(BANK)), invested: '0.00', assets: String(round(assetsAt0)) },
  ]
  // Surplus waterfall (mirrors backend): positive months invest; negative
  // months drain cash first, then investments; shortfall never compounds.
  let cash = BANK
  let invested = 0
  // Already there today — mirror the backend's day-0 check.
  let target_date: string | null = target != null && NET_WORTH >= target ? addM(0) : null
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
    const value = cash + invested + assetsValue
    if (target != null && !target_date && value >= target) {
      target_date = addM(m)
      monthsWanted = Math.min(600, m + 6)
    }
    if (m <= monthsWanted)
      timeline.push({
        date: addM(m),
        value: String(round(value)),
        cash: String(round(cash)),
        invested: String(round(invested)),
        assets: String(round(assetsValue)),
      })
    else if (target == null || target_date) break
  }
  return {
    current_net_worth: String(round(NET_WORTH)),
    target_amount: target != null ? String(target) : null,
    target_date,
    monthly_contribution: String(round(monthly)),
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

function instrumentsSearchResponse(q: string) {
  const all = [
    { id: 'sinst-btc', symbol: 'BTC', name: 'Bitcoin', kind: 'crypto', provider: 'coingecko', currency: 'GBP' },
    { id: 'sinst-eth', symbol: 'ETH', name: 'Ethereum', kind: 'crypto', provider: 'coingecko', currency: 'GBP' },
    { id: 'sinst-vusa', symbol: 'VUSA.LON', name: 'Vanguard S&P 500 ETF', kind: 'etf', provider: 'alphavantage', currency: 'GBX' },
  ]
  const s = (q || '').toLowerCase()
  return all.filter((i) => i.symbol.toLowerCase().includes(s) || i.name.toLowerCase().includes(s))
}

function assetsResponse() {
  return ASSETS.map((a) => ({
    id: a.id, name: a.name, asset_type: a.asset_type,
    assumed_growth_pct: null,
    monthly_contribution: a.monthly ? String(a.monthly) : null,
    instrument: a.instrument ?? null,
    units: a.units != null ? String(a.units) : null,
    unit_price_gbp: a.unit_price_gbp != null ? String(a.unit_price_gbp) : null,
    priced_at: a.unit_price_gbp != null ? new Date().toISOString() : null,
    valuations: [
      // Assets grow over time; liabilities (negative) get paid down, so the
      // older figure is further from zero in both cases.
      { id: `${a.id}-v0`, value: String(Math.round(a.value * (a.value < 0 ? 1.15 : 0.9))), valued_at: isoDate(nowMinus(180)) },
      { id: `${a.id}-v1`, value: String(a.value), valued_at: isoDate(nowMinus(40)) },
    ],
  }))
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
  if (is('/analytics/planned-items')) return [{ id: 'sp1', name: 'New laptop', direction: 'expense', kind: 'installment_plan', start_date: isoDate(nowPlus(9)), amount: null, total_amount: 1200, installments: 6 }]
  if (is('/analytics/nudges')) return nudgesResponse()
  if (path.includes('/analytics/net-worth-decomposition')) return decompositionResponse(Number(p.months) || 12)
  if (path.includes('/analytics/net-worth-projection')) return projectionResponse(p as Record<string, any>)
  if (path.includes('/analytics/net-worth-history')) return netWorthHistory(Number(p.months) || 12)
  if (is('/instruments/search')) return instrumentsSearchResponse(String(p.q ?? ''))
  if (is('/assets')) return assetsResponse()
  if (is('/rules')) return { packs: [], personal: [] }
  return {}
}
