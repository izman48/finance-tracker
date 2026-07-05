// Verify the stat-explainer tooltips: every InfoTip trigger opens a tooltip
// with non-empty text on hover (desktop) and tap (mobile). Reuses the
// visual-check API mocks. Run with the dev server up:
//   BASE_URL=http://localhost:5199 node scripts/tooltip-check.mjs
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
  { id: 'a3', display_name: 'Amex Gold', provider_name: 'American Express', account_type: 'CREDIT_CARD', role: 'credit', current_balance: -642.31, overdraft_limit: null, repayment_cadence: 'end_of_month', repayment_day: null, repayment_interval_months: null, repayment_anchor_date: null, repayment_strategy: 'full_balance', repayment_installments: null, pay_from_account_id: 'a1' },
]
const summary = {
  available_cash: 2140.55, overdraft_cushion: 500, credit_owed: 642.31, net_worth: 10298.24,
  savings_total: 8800, assets_total: 9000,
  committed_before_payday: 893.4, safe_to_spend: 1247.15, savable: 410, next_payday: daysFromNow(16),
  next_repayments: [{ account_id: 'a3', label: 'Amex Gold', amount: 642.31, due_date: daysFromNow(9) }],
  accounts,
}
const timeline = Array.from({ length: 31 }, (_, i) => ({ date: daysFromNow(i), balance: 2140 - i * 55, events: [] }))
const forecast = { horizon: '30', horizon_end: daysFromNow(30), start_balance: 2140.55, end_balance: timeline[30].balance, min_balance: Math.min(...timeline.map((p) => p.balance)), min_date: daysFromNow(15), overdraft_limit: 500, breaches: [], timeline }
const spending = { period: 'since_payday', period_start: daysFromNow(-14), period_end: iso(today), total_spent: 1086.42, charged_to_credit: 402.1, paid_from_cash: 684.32, by_category: [{ category: 'Groceries', total: 284.5, count: 12 }], top_merchants: [{ merchant: 'Tesco', total: 182.4 }] }
const trend = { months: [{ month: '2026-06', total: 1500, charged_to_credit: 400, paid_from_cash: 1100 }] }
const netWorthHistory = Array.from({ length: 12 }, (_, i) => { const d = new Date(today.getFullYear(), today.getMonth() - (11 - i), 1); return { date: iso(d), bank: '6000', assets: '2000', net_worth: String(8000 + i * 400) } })

const routes = [
  ['**/api/v1/auth/me', { id: 'u1', email: 'demo@example.com' }],
  ['**/api/v1/banking/status', { is_connected: true, connections_count: 1, last_synced_at: new Date().toISOString(), connections: [], message: 'ok' }],
  ['**/api/v1/analytics/summary', summary],
  ['**/api/v1/analytics/forecast*', forecast],
  ['**/api/v1/analytics/spending/trend*', trend],
  ['**/api/v1/analytics/spending*', spending],
  ['**/api/v1/analytics/commitments', []],
  ['**/api/v1/analytics/planned-items', []],
  ['**/api/v1/analytics/net-worth-history*', netWorthHistory],
  ['**/api/v1/assets', []],
  ['**/api/v1/banking/accounts', []],
  ['**/api/v1/banking/transactions*', { items: [], total: 0 }],
  ['**/api/v1/rules', { packs: [], personal: [] }],
]

const PAGES = [
  ['dashboard', '/dashboard'],
  ['insights', '/insights'],
  ['networth', '/networth'],
]

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const failures = []
let checked = 0

for (const [mode, viewport, useTap] of [
  ['desktop', { width: 1440, height: 900 }, false],
  ['mobile', { width: 390, height: 844 }, true],
]) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, hasTouch: useTap })
  for (const [pattern, body] of routes) {
    await ctx.route(pattern, (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }))
  }
  await ctx.addInitScript(() => localStorage.setItem('token', 'mock-token'))
  const page = await ctx.newPage()

  for (const [name, path] of PAGES) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(800)
    const triggers = page.locator('[aria-label="How is this calculated?"]')
    const n = await triggers.count()
    if (n === 0) failures.push(`[${mode}] ${name}: no InfoTip triggers found`)
    for (let i = 0; i < n; i++) {
      const t = triggers.nth(i)
      await t.scrollIntoViewIfNeeded()
      if (useTap) await t.tap()
      else await t.hover()
      await page.waitForTimeout(120)
      const tip = page.locator('[role="tooltip"]')
      const visible = (await tip.count()) === 1 && (await tip.first().innerText()).trim().length > 20
      if (!visible) failures.push(`[${mode}] ${name}: trigger #${i} did not open a tooltip`)
      else checked++
      if (i === 0) await page.screenshot({ path: `${OUT}/tooltip-${name}-${mode}.png` })
      if (useTap) await t.tap() // close before the next one
      else await page.mouse.move(0, 0)
      await page.waitForTimeout(80)
    }
  }
  await ctx.close()
}

await browser.close()
console.log(`${checked} tooltips verified`)
if (failures.length) {
  for (const f of failures) console.log(' FAIL:', f)
  process.exit(1)
}
console.log('ALL OK')
