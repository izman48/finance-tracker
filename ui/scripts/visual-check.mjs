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
  { id: 'a1', display_name: 'Monzo Current', provider_name: 'Monzo', account_type: 'TRANSACTION', role: 'spending', current_balance: 2140.55, overdraft_limit: 500, repayment_cadence: null, repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: null, repayment_installments: null, pay_from_account_id: null },
  { id: 'a2', display_name: 'Marcus Savings', provider_name: 'Goldman Sachs', account_type: 'SAVINGS', role: 'savings', current_balance: 8800, overdraft_limit: null, repayment_cadence: null, repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: null, repayment_installments: null, pay_from_account_id: null },
  { id: 'a3', display_name: 'Amex Gold', provider_name: 'American Express', account_type: 'CREDIT_CARD', role: 'credit', current_balance: -642.31, overdraft_limit: null, repayment_cadence: 'end_of_month', repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: 'full_balance', repayment_installments: null, pay_from_account_id: 'a1' },
]

const summary = {
  available_cash: 2140.55,
  overdraft_cushion: 500,
  credit_owed: 642.31,
  net_worth: 10298.24,
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
  breaches: [],
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
  { id: 'c7', direction: 'income', label: 'Annual bonus', amount: 1500, cadence: 'every_n_months', interval_days: null, interval_months: 12, next_date: daysFromNow(200), source: 'manual', status: 'confirmed', account_id: 'a1' },
]

const planned = [
  { id: 'p1', name: 'New laptop', direction: 'expense', kind: 'installment_plan', start_date: daysFromNow(10), amount: null, total_amount: 1200, installments: 6 },
  { id: 'p2', name: 'Tax refund', direction: 'income', kind: 'one_off', start_date: daysFromNow(21), amount: 350, total_amount: null, installments: null },
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

const assets = [
  { id: 'as1', name: 'Vanguard S&S ISA', asset_type: 'isa', valuations: [{ id: 'v1', value: '4200', valued_at: daysFromNow(-200) }, { id: 'v2', value: '4650', valued_at: daysFromNow(-10) }] },
  { id: 'as2', name: 'Workplace pension', asset_type: 'pension', valuations: [{ id: 'v3', value: '5400', valued_at: daysFromNow(-30) }] },
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

const routes = [
  ['**/api/v1/auth/me', { id: 'u1', email: 'demo@example.com' }],
  ['**/api/v1/banking/status', { is_connected: true, connections_count: 2, last_synced_at: new Date(Date.now() - 42 * 60000).toISOString(), connections: [ { id: 'b1', provider_name: 'Monzo', is_expired: false, expires_at: null }, { id: 'b2', provider_name: 'American Express', is_expired: false, expires_at: null } ], message: 'ok' }],
  ['**/api/v1/analytics/summary', summary],
  ['**/api/v1/analytics/forecast*', forecast],
  ['**/api/v1/analytics/spending/trend*', trend],
  ['**/api/v1/analytics/spending*', spending],
  ['**/api/v1/analytics/commitments', commitments],
  ['**/api/v1/analytics/planned-items', planned],
  ['**/api/v1/analytics/net-worth-history*', netWorthHistory],
  ['**/api/v1/assets', assets],
  ['**/api/v1/banking/accounts', accounts.map(({ id, display_name, provider_name, account_type }) => ({ id, display_name, provider_name, account_type }))],
  ['**/api/v1/banking/transactions*', { items: transactions, total: transactions.length }],
  ['**/api/v1/rules', rules],
]

const pages = [
  ['home', '/', false],
  ['login', '/login', false],
  ['dashboard', '/dashboard', true],
  ['transactions', '/transactions', true],
  ['insights', '/insights', true],
  ['commitments', '/commitments', true],
  ['networth', '/networth', true],
  ['rules', '/rules', true],
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
    if (res.status() >= 400) errors.push(`[${vpName}] HTTP ${res.status()} ${res.url()}`)
  })

  for (const [name, path] of pages) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1600) // let gsap entrances finish
    await page.screenshot({ path: `${OUT}/${name}-${vpName}.png`, fullPage: true })
    console.log(`shot ${name}-${vpName}`)
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
