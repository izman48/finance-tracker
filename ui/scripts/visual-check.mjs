// Visual verification: drives the app in Chrome with mocked API responses and
// screenshots every page at desktop + mobile sizes. Run with the dev server up:
//   node scripts/visual-check.mjs
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const BASE = process.env.BASE_URL || 'http://localhost:5173'
const OUT = '/tmp/ui-shots'
mkdirSync(OUT, { recursive: true })

const today = new Date()
const iso = (d) => d.toISOString().slice(0, 10)
const daysFromNow = (n) => iso(new Date(today.getTime() + n * 86400000))

const accounts = [
  { id: 'a1', display_name: 'Monzo Current', provider_name: 'Monzo', account_type: 'TRANSACTION', role: 'spending', current_balance: 2140.55, credit_owed: null, overdraft_limit: 500, repayment_cadence: null, repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: null, repayment_installments: null, pay_from_account_id: null },
  { id: 'a2', display_name: 'Marcus Savings', provider_name: 'Goldman Sachs', account_type: 'SAVINGS', role: 'savings', current_balance: 8800, credit_owed: null, overdraft_limit: null, repayment_cadence: null, repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: null, repayment_installments: null, pay_from_account_id: null },
  { id: 'a3', display_name: 'Amex Gold', provider_name: 'American Express', account_type: 'CREDIT_CARD', role: 'credit', current_balance: 642.31, credit_owed: 642.31, overdraft_limit: null, repayment_cadence: 'end_of_month', repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: 'full_balance', repayment_installments: null, pay_from_account_id: 'a1',
    // T-10-14: the card's statement (statement £500.00 due in 9 days, synthetic).
    statement: { statement_balance: '500.00', due_date: daysFromNow(9), paid: false, missing: false } },
  // No repayment set up: not in the forecast, so Home, Cashflow and its
  // settings show the D8 notice (T-10-12). No statement entered either.
  { id: 'a4', display_name: 'Harbor Card', provider_name: 'Harbor Bank', account_type: 'CREDIT_CARD', role: 'credit', current_balance: 180, credit_owed: 180, overdraft_limit: null, repayment_cadence: null, repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: null, repayment_installments: null, pay_from_account_id: null, statement: null },
]

const summary = {
  available_cash: 2140.55,
  overdraft_cushion: 500,
  credit_owed: 822.31,
  // T-10-14a: cards plus loans, from the server (822.31 + the liabilities below).
  total_owed: '15322.31',
  net_worth: 10118.24,
  committed_before_payday: 893.4,
  safe_to_spend: 1247.15,
  savable: 410,
  next_payday: daysFromNow(16),
  next_repayments: [
    { account_id: 'a3', label: 'Amex Gold', amount: 642.31, due_date: daysFromNow(9) },
  ],
  accounts,
}

const timeline = Array.from({ length: 31 }, (_, i) => ({
  date: daysFromNow(i),
  balance: 2140 - i * 55 + (i % 7 === 0 ? 300 : 0) + (i === 16 ? 3200 : 0),
  events: i === 16 ? [{ label: 'Salary', amount: 3200, kind: 'income' }] : [],
}))

const forecast = {
  horizon: '30',
  horizon_end: daysFromNow(30),
  start_balance: 2140.55,
  end_balance: timeline[30].balance,
  min_balance: Math.min(...timeline.map((p) => p.balance)),
  min_date: daysFromNow(15),
  overdraft_limit: 500,
  // Pooled fine, one account past its own limit: the per-account lines,
  // the pooled-ok note and the "estimated" footnote all render.
  breaches: ['overdraft'],
  account_breaches: [
    { account_id: 'a1', account_name: 'Monzo Current', date: daysFromNow(9), balance: '-620.00', floor: '-500', kind: 'overdraft' },
  ],
  unassigned_attributed_to: 'a1',
  timeline,
}

const spending = {
  period: 'since_payday',
  period_start: daysFromNow(-14),
  period_end: iso(today),
  total_spent: 1086.42,
  charged_to_credit: 402.1,
  paid_from_cash: 684.32,
  by_category: [
    { category: 'Groceries', total: 284.5, count: 12 },
    { category: 'Eating out', total: 196.4, count: 9 },
    { category: 'Transport', total: 142.3, count: 15 },
    { category: 'Subscriptions', total: 89.97, count: 6 },
    { category: 'Shopping', total: 230.25, count: 4 },
    { category: 'Other', total: 143.0, count: 7 },
  ],
  top_merchants: [
    { merchant: 'Tesco', total: 182.4 },
    { merchant: 'Deliveroo', total: 96.2 },
    { merchant: 'TfL', total: 88.7 },
    { merchant: 'Amazon', total: 154.99 },
    { merchant: 'Pret a Manger', total: 42.6 },
  ],
}

const trend = {
  months: Array.from({ length: 6 }, (_, i) => {
    const d = new Date(today.getFullYear(), today.getMonth() - (5 - i), 1)
    return {
      month: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`,
      total: 1500 + ((i * 137) % 600),
      charged_to_credit: 400 + ((i * 53) % 200),
      paid_from_cash: 1100 + ((i * 84) % 400),
    }
  }),
}

const commitments = [
  { id: 'c1', direction: 'income', label: 'Salary', amount: 3200, cadence: 'monthly', interval_days: null, interval_months: null, next_date: daysFromNow(16), source: 'detected', status: 'confirmed', account_id: 'a1' },
  { id: 'c2', direction: 'expense', label: 'Rent', amount: 1100, cadence: 'monthly', interval_days: null, interval_months: null, next_date: daysFromNow(19), source: 'detected', status: 'confirmed', account_id: 'a1' },
  { id: 'c3', direction: 'expense', label: 'Netflix', amount: 10.99, cadence: 'monthly', interval_days: null, interval_months: null, next_date: daysFromNow(4), source: 'detected', status: 'suggested', account_id: 'a1' },
  { id: 'c4', direction: 'expense', label: 'Gym', amount: 32, cadence: 'monthly', interval_days: null, interval_months: null, next_date: daysFromNow(7), source: 'detected', status: 'confirmed', account_id: 'a1' },
  { id: 'c5', direction: 'expense', label: 'Car insurance', amount: 540, cadence: 'every_n_months', interval_days: null, interval_months: 12, next_date: daysFromNow(80), source: 'manual', status: 'confirmed', account_id: 'a1' },
  { id: 'c6', direction: 'expense', label: 'Amazon Prime', amount: 95, cadence: 'every_n_months', interval_days: null, interval_months: 12, next_date: daysFromNow(30), source: 'manual', status: 'confirmed', account_id: 'a1' },
  // Linked to loan li1 below, so Home's Coming up reads "Lender A loan payment".
  { id: 'c-li1', direction: 'expense', label: 'Lender A', amount: 200, cadence: 'monthly', interval_days: null, interval_months: null, next_date: daysFromNow(3), source: 'manual', status: 'confirmed', account_id: 'a1' },
  { id: 'c7', direction: 'income', label: 'Annual bonus', amount: 1500, cadence: 'every_n_months', interval_days: null, interval_months: 12, next_date: daysFromNow(200), source: 'manual', status: 'confirmed', account_id: 'a1' },
]

const planned = [
  { id: 'p1', name: 'New laptop', direction: 'expense', kind: 'installment_plan', start_date: daysFromNow(10), amount: null, total_amount: 1200, installments: 6, cadence: 'monthly', interval_days: null, interval_months: null, end_date: null, apr: null, fee_amount: null, active: true },
  { id: 'p2', name: 'Tax refund', direction: 'income', kind: 'one_off', start_date: daysFromNow(21), amount: 350, total_amount: null, installments: null, cadence: null, interval_days: null, interval_months: null, end_date: null, apr: null, fee_amount: null, active: true },
  { id: 'p3', name: 'Piano lessons', direction: 'expense', kind: 'recurring', start_date: daysFromNow(5), amount: 90, total_amount: null, installments: null, cadence: 'monthly', interval_days: null, interval_months: null, end_date: null, apr: null, fee_amount: null, active: true },
]

const merchants = ['Tesco', 'Deliveroo', 'TfL', 'Amazon', 'Pret a Manger', 'Spotify', 'Netflix']
const cats = ['Groceries', 'Eating out', 'Transport', 'Subscriptions', null]
const transactions = Array.from({ length: 60 }, (_, i) => ({
  id: `t${i}`,
  account_id: accounts[i % 3].id,
  transaction_type: i % 5 === 0 ? 'credit' : 'debit',
  amount: Math.round((8 + ((i * 7.13) % 120)) * 100) / 100,
  currency: 'GBP',
  description: `${merchants[i % merchants.length].toUpperCase()} *PAYMENT ${1000 + i}`,
  merchant_name: merchants[i % merchants.length],
  category: cats[i % cats.length],
  subcategory: null,
  is_recurring: i % 11 === 0,
  is_commitment: i % 6 === 0,
  is_financed: false,
  excluded_reason: i % 13 === 0 ? 'card_payment' : i % 17 === 0 ? 'internal_transfer' : null,
  transaction_date: daysFromNow(-i),
}))

const netWorthHistory = Array.from({ length: 12 }, (_, i) => {
  const d = new Date(today.getFullYear(), today.getMonth() - (11 - i), 1)
  return {
    date: iso(d),
    bank: String(6000 + i * 220),
    assets: String(2000 + i * 180),
    net_worth: String(8000 + i * 400),
  }
})

const position = {
  as_of: iso(today),
  net_worth: '12400',
  bank: '8420',
  assets: '3980',
  liabilities: '14500',
  since: iso(new Date(today.getFullYear() - 1, today.getMonth() - 2, 1)),
  changes: [
    { key: '1m', label: '1 month', from_date: iso(new Date(today.getFullYear(), today.getMonth() - 1, today.getDate())), available: true, from_value: '12000', change: '400', change_pct: '3.3' },
    { key: '3m', label: '3 months', from_date: iso(new Date(today.getFullYear(), today.getMonth() - 3, today.getDate())), available: true, from_value: '11200', change: '1200', change_pct: '10.7' },
    { key: '6m', label: '6 months', from_date: iso(new Date(today.getFullYear(), today.getMonth() - 6, today.getDate())), available: true, from_value: '12800', change: '-400', change_pct: '-3.1' },
    { key: '1y', label: '1 year', from_date: iso(new Date(today.getFullYear() - 1, today.getMonth(), today.getDate())), available: true, from_value: '8000', change: '4400', change_pct: '55.0' },
    { key: 'all', label: 'All time', from_date: iso(new Date(today.getFullYear() - 1, today.getMonth() - 2, 1)), available: true, from_value: '7600', change: '4800', change_pct: '63.2' },
  ],
}

const assets = [
  { id: 'as1', name: 'Vanguard S&S ISA', asset_type: 'isa', valuations: [{ id: 'v1', value: '4200', valued_at: daysFromNow(-200) }, { id: 'v2', value: '4650', valued_at: daysFromNow(-10) }] },
  { id: 'as2', name: 'Workplace pension', asset_type: 'pension', valuations: [{ id: 'v3', value: '5400', valued_at: daysFromNow(-30) }] },
]

// Loans and finance (T-10-10): a linked loan, a stale finance balance and an
// irregular loan, to show every row shape. Synthetic figures only.
const liability = (over) => ({
  id: 'li1', kind: 'loan', lender: 'Lender A', balance: '9000.00', balance_as_of: daysFromNow(-5), apr: '11.00',
  payment: '200.00', cadence: 'monthly', start_date: daysFromNow(10), end_date: null, opted_out: false,
  current_balance: '9000.00', next_payment_date: daysFromNow(10), payments_remaining: 58, payoff_date: daysFromNow(1735),
  interest_remaining: '2483.22', total_cost: '11483.22', paid_off: false, balance_stale: false,
  linked_commitment: { id: 'c-li1', label: 'Lender A' }, link_result: null, ...over,
})
const liabilities = [
  liability({ id: 'li2', kind: 'finance', lender: 'Lender B with a rather long trading name', balance: '1500.00', current_balance: '1500.00', apr: '20.00', payment: '100.00', interest_remaining: '139.41', balance_stale: true, balance_as_of: daysFromNow(-120), linked_commitment: { id: 'c-li2', label: 'Lender B' } }),
  liability({}),
  liability({ id: 'li3', lender: 'Lender C', balance: '4000.00', current_balance: '4000.00', apr: '5.00', payment: null, opted_out: true, payoff_date: null, interest_remaining: null, total_cost: null, payments_remaining: null, next_payment_date: null, linked_commitment: null }),
]

const rules = {
  packs: [
    {
      id: 'pk1', name: 'UK Essentials', description: 'Supermarkets, transport, utilities', share_code: 'AB12CD', imported_from: null, enabled: true,
      rules: [
        { id: 'r1', pack_id: 'pk1', pattern: 'tesco', match_type: 'contains', match_field: 'any', category: 'Groceries', source: 'manual', enabled: true },
        { id: 'r2', pack_id: 'pk1', pattern: 'tfl', match_type: 'contains', match_field: 'any', category: 'Transport', source: 'manual', enabled: true },
      ],
    },
  ],
  personal: [
    { id: 'r3', pack_id: null, pattern: 'Deliveroo', match_type: 'exact', match_field: 'merchant', category: 'Eating out', source: 'learned', enabled: true },
  ],
}

// Card statement block (T-10-6), one body per display state. Synthetic:
// statement £500.00 against the mocked card's £642.31 owed, so £142.31 was
// spent since the statement.
const statementRow = (over = {}) => ({
  id: 'st1', account_id: 'a3', statement_balance: '500.00', statement_date: daysFromNow(-20),
  due_date: daysFromNow(9), minimum_due: '25.00', source: 'manual', ...over,
})
const statementPosition = (over = {}) => ({
  statement_id: 'st1', source: 'manual', statement_balance: '500.00', statement_date: daysFromNow(-20),
  due_date: daysFromNow(9), minimum_due: '25.00', payments_since_statement: '0.00', amount_still_due: '500.00',
  unbilled: '142.31', paid: false, ...over,
})
const nextPayment = { amount: '500.00', date: daysFromNow(9), from_account_name: 'Monzo Current' }
const statementStates = {
  populated: { statements: [statementRow()], current: statementPosition(), missing_statement: false, conflict: false, next_payment: nextPayment },
  paid: {
    statements: [statementRow()], current: statementPosition({ payments_since_statement: '500.00', amount_still_due: '0.00', paid: true }),
    missing_statement: false, conflict: false, next_payment: { ...nextPayment, amount: '142.31', date: daysFromNow(39) },
  },
  missing: {
    statements: [statementRow({ statement_date: daysFromNow(-40), due_date: daysFromNow(-3) })],
    current: statementPosition({ statement_date: daysFromNow(-40), due_date: daysFromNow(-3) }),
    missing_statement: true, conflict: false, next_payment: { ...nextPayment, amount: '642.31', date: daysFromNow(27) },
  },
  conflict: {
    statements: [statementRow(), statementRow({ id: 'st2', statement_balance: '490.00', source: 'provider' })],
    current: statementPosition(), missing_statement: false, conflict: true, next_payment: nextPayment,
  },
  empty: { statements: [], current: null, missing_statement: false, conflict: false, next_payment: { ...nextPayment, amount: '642.31', date: daysFromNow(30) } },
}

const routes = [
  ['**/api/v1/auth/me', { id: 'u1', email: 'demo@example.com' }],
  ['**/api/v1/banking/status', { is_connected: true, connections_count: 2, last_synced_at: new Date(Date.now() - 42 * 60000).toISOString(), connections: [ { id: 'b1', provider_name: 'Monzo', is_expired: false, expires_at: null }, { id: 'b2', provider_name: 'American Express', is_expired: true, expires_at: null } ], message: 'ok' }],
  ['**/api/v1/analytics/summary', summary],
  ['**/api/v1/analytics/forecast*', forecast],
  ['**/api/v1/analytics/spending/trend*', trend],
  ['**/api/v1/analytics/spending*', spending],
  ['**/api/v1/analytics/commitments', commitments],
  ['**/api/v1/analytics/planned-items', planned],
  ['**/api/v1/analytics/net-worth-history*', netWorthHistory],
  ['**/api/v1/analytics/net-worth-position', position],
  ['**/api/v1/analytics/net-worth-decomposition*', { start_date: iso(new Date(today.getFullYear() - 1, today.getMonth(), today.getDate())), end_date: iso(today), assets_start: '2000', assets_end: '3980', assets_delta: '1980', contributions: '1500', growth: '480', flows_recorded: 3 }],
  ['**/api/v1/analytics/nudges', []],
  ['**/api/v1/assets', assets],
  ['**/api/v1/liabilities', liabilities],
  ['**/api/v1/banking/accounts', accounts.map(({ id, display_name, provider_name, account_type }) => ({ id, display_name, provider_name, account_type }))],
  ['**/api/v1/banking/transactions*', { items: transactions, total: transactions.length, page: 1, page_size: 100 }],
  // Registered after transactions* — Playwright checks later routes first.
  ['**/api/v1/banking/transactions/facets', { categories: cats.filter(Boolean), merchants }],
  // Resume-sync fires these on mount when data is stale; mock so networkidle settles.
  ['**/api/v1/banking/sync/accounts', { synced: true, accounts: [] }],
  ['**/api/v1/banking/sync/transactions', { synced: true, count: 0 }],
  ['**/api/v1/rules', rules],
  ['**/api/v1/analytics/accounts/a4/statements', statementStates.empty],
  ['**/api/v1/oauth/authorize/details*', { client_name: 'Claude Code', redirect_host: 'localhost:33418', requested_scopes: ['finance:read'] }],
]

const pages = [
  ['home', '/', false],
  ['login', '/login', false],
  ['register', '/register', false],
  ['privacy', '/privacy', false],
  ['terms', '/terms', false],
  ['overview', '/home', true],
  ['dashboard', '/dashboard', true],
  ['transactions', '/transactions', true],
  ['insights', '/insights', true],
  ['commitments', '/commitments', true],
  ['networth', '/networth', true],
  ['rules', '/rules', true],
  ['oauth-consent', '/oauth/authorize?client_id=c&redirect_uri=http%3A%2F%2Flocalhost%3A33418%2Fcallback', true],
]

const viewports = [
  ['desktop', { width: 1440, height: 900 }],
  ['tablet', { width: 820, height: 1180 }],
  ['tablet-land', { width: 1180, height: 820 }],
  ['mobile', { width: 390, height: 844 }],
]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const errors = []

for (const [vpName, viewport] of viewports) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2 })
  for (const [pattern, body] of routes) {
    await ctx.route(pattern, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }),
    )
  }
  await ctx.addInitScript(() => localStorage.setItem('token', 'mock-token'))

  const page = await ctx.newPage()
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`[${vpName}] ${page.url()}: ${msg.text()}`)
  })
  page.on('pageerror', (err) => errors.push(`[${vpName}] ${page.url()}: PAGEERROR ${err.message}`))
  page.on('response', (res) => {
    // The loan form's 409 choose_commitment is staged on purpose (below).
    if (res.status() === 409 && res.url().endsWith('/api/v1/liabilities')) return
    if (res.status() >= 400) errors.push(`[${vpName}] HTTP ${res.status()} ${res.url()}`)
  })

  for (const [name, path] of pages) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1600) // let gsap entrances finish
    await page.screenshot({ path: `${OUT}/${name}-${vpName}.png`, fullPage: true })
    console.log(`shot ${name}-${vpName}`)
  }
  // The card settings modal, once per statement state (desktop and mobile).
  if (vpName === 'desktop' || vpName === 'mobile') {
    for (const [state, body] of Object.entries(statementStates)) {
      await page.route('**/api/v1/analytics/accounts/a3/statements', (route) =>
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }),
      )
      await page.goto(`${BASE}/networth`, { waitUntil: 'networkidle' })
      await page.waitForTimeout(1600)
      await page.getByText('Amex Gold').first().click()
      await page.getByRole('dialog').waitFor()
      await page.waitForTimeout(400)
      await page.screenshot({ path: `${OUT}/card-statement-${state}-${vpName}.png`, fullPage: true })
      console.log(`shot card-statement-${state}-${vpName}`)
      await page.unroute('**/api/v1/analytics/accounts/a3/statements')
    }
  }
  // T-10-12: Home's notice opens that card's settings on Wealth.
  if (vpName === 'desktop' || vpName === 'mobile') {
    await page.goto(`${BASE}/home`, { waitUntil: 'networkidle' })
    await page.getByRole('link', { name: /Harbor Card/ }).click()
    await page.getByRole('dialog', { name: 'Harbor Card' }).waitFor()
    if (new URL(page.url()).search) errors.push(`[${vpName}] settings link left ${page.url()}`)
    await page.waitForTimeout(400)
    await page.screenshot({ path: `${OUT}/card-not-set-up-${vpName}.png`, fullPage: true })
    console.log(`shot card-not-set-up-${vpName}`)
    // T-10-14b: Cashflow's "Add statement" opens that card's settings too.
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle' })
    await page.getByRole('link', { name: 'Add statement' }).click()
    await page.getByRole('dialog', { name: 'Harbor Card' }).waitFor()
    if (new URL(page.url()).search) errors.push(`[${vpName}] Add statement left ${page.url()}`)
    console.log(`flow add-statement-${vpName} ok`)
  }
  // The loan form (T-10-10b): edit a linked loan, add one, and the
  // "Which bill is this?" step after a 409 choose_commitment.
  if (vpName === 'desktop' || vpName === 'mobile') {
    await page.goto(`${BASE}/networth`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1600)
    await page.getByText('Lender A').first().click()
    await page.getByRole('dialog').waitFor()
    await page.screenshot({ path: `${OUT}/loan-form-edit-${vpName}.png`, fullPage: true })
    console.log(`shot loan-form-edit-${vpName}`)
    await page.keyboard.press('Escape')

    await page.route('**/api/v1/liabilities', (route) =>
      route.request().method() === 'POST'
        ? route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: {
            code: 'choose_commitment', message: 'Choose one.', candidates: [
              { id: 'c1', label: 'LOAN DD', amount: '200.00', cadence: 'monthly', interval_days: null, next_date: daysFromNow(9) },
              { id: 'c2', label: 'Lender A repayment', amount: '200.00', cadence: 'monthly', interval_days: null, next_date: daysFromNow(12) },
            ] } }) })
        : route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(liabilities) }),
    )
    await page.getByRole('button', { name: 'Add', exact: true }).first().click()
    await page.getByText('Add a loan or finance').first().click()
    await page.getByRole('dialog').waitFor()
    await page.screenshot({ path: `${OUT}/loan-form-add-${vpName}.png`, fullPage: true })
    console.log(`shot loan-form-add-${vpName}`)
    await page.fill('#liability-lender', 'Lender D')
    await page.fill('#liability-balance', '9000.00')
    await page.fill('#liability-apr', '11')
    await page.fill('#liability-payment', '200.00')
    await page.fill('#liability-start-date', daysFromNow(10))
    await page.getByRole('button', { name: 'Add loan' }).click()
    await page.getByRole('heading', { name: 'Which bill is this loan?' }).waitFor()
    await page.screenshot({ path: `${OUT}/loan-form-picker-${vpName}.png`, fullPage: true })
    console.log(`shot loan-form-picker-${vpName}`)
    await page.unroute('**/api/v1/liabilities')
  }
  await ctx.close()
}

await browser.close()
if (errors.length) {
  console.log('\nCONSOLE ERRORS:')
  for (const e of errors) console.log(' -', e)
} else {
  console.log('\nNo console errors.')
}
