# Safe to spend and forecast (Cashflow tab)

The headline figures (available cash, overdraft cushion, credit owed,
committed before payday, **safe to spend**, savable, next payday, next card
repayments) and a day-by-day balance forecast with its low point, overdraft
or zero breaches, late income and the budget projection.

## Code

**API** (`api/app/routers/analytics.py`):

| Route | Auth | Notes |
|---|---|---|
| `GET /api/v1/analytics/summary` | `CurrentUserOrMcpRead` | Also returns the totals Claude's unkept changes are holding back, `total_owed` (cards + liabilities) and each card's current `statement` (T-10-14a, see accounts.md). |
| `GET /api/v1/analytics/forecast` | `CurrentUserOrMcpRead` | `horizon` = `payday` (default), `month` or N days (max 730). Adds `late_income`, `late_planned`, `budget_projection`. |
| `GET /api/v1/plan` | `CurrentUser` (web only), `limit_user("plan")` | Plan (T-24-4): income, Fixed, Budgets and Not planned for the pay cycle; see "Plan" below. |

**Tables**: none of its own. Reads `accounts`, `account_settings`,
`commitment_rules`, `planned_items`, `repayment_schedule_items`, `assets`,
`asset_valuations`, `audit_entries`, `transactions`, `budgets`. Reading
summary or forecast may write card links on `commitment_rules`
(`card_links.py`).

**Services**: `services/analytics/summary.py`, `forecast.py`,
`late_income.py`, `commitments.py` (payday helpers), `repayments.py`,
`planned.py`, `planned_matching.py`, `services/claude_keep.py`,
`services/budgets.budget_projection`. `analytics_service.py` is a
compatibility shim over `services/analytics/`.

**Rules worth knowing**: planned income never raises safe to spend; Claude's
changes to income can't raise it until the user keeps them
(`test_no_claude_raise.py`), and the forecast holds them the same way (T-12-9a): its payday horizon, its daily balances and the budget cycle behind the "after budgets" strip all keep payday where it was before Claude until the change is kept (T-12-9d); budgets never change any money figure
(`test_budget_invariance.py`).

**UI**: `/dashboard` (`DashboardPage`: safe-to-spend and savable tiles,
`ForecastChart`, `ForecastSummary`, `forecast/LateIncomeNote`,
`forecast/BudgetStrip`, `forecast/ForecastError`, `NudgeFeed`),
`lib/forecastLoad.ts`, `lib/late.ts`, `lib/budgetProjection.ts`,
`lib/upcoming.ts`. Home Cashflow card. Accounts (T-10-14b, ux T-10-13):
`components/cashflow/AccountGroups.tsx` + `lib/cashflowGroups.ts` list
Current accounts, Savings and Credit cards as labelled sections, in that
order, each with a subtotal (the cards' is the API's `credit_owed`); the
hero line counts current and savings accounts only. A card's figure says
"owed" or "in credit", and its second line is its statement
(`lib/cardStatement.ts`), with Add statement / Add new linking to its
settings. A card that owes money with no repayment set up shows "Repayment
not set up" under its row, with a link to its settings (T-10-12, see
accounts.md); on Home several such cards share one notice. A bill linked to a loan reads "{lender} loan payment" in
Coming up and in the forecast's event list (P2, `lib/loanLabel.ts` with
`homeOwed.loanPaymentLabel`): built in the browser from the liabilities list
(`linked_commitment`, see liabilities.md), so the label never reaches Claude. Both match on the
commitment id: forecast income/expense events carry `commitment_id` (null for
repayments and planned items). A card plan's instalment plus fee is a
repayment event labelled "{plan} instalment" on the card's next pay day
(or its own date with no pay day), counted in safe-to-spend whatever the
provider's status (T-12-5b, see liabilities.md).

**MCP**: `cashflow_summary`, `forecast` (tool default horizon is `"90"`).

**Tests**: `api/tests/unit/test_analytics_service.py`,
`test_card_repayment_once.py`, `test_card_installments.py`;
`api/tests/integration/test_late_income.py`, `test_late_split_payment.py`,
`test_planned_matching.py`, `test_budget_projection.py`,
`test_budget_invariance.py`, `test_no_claude_raise.py`,
`test_claude_income_parity.py`, `test_income_write_block.py`; UI
`ForecastSummary.test.tsx`, `LateIncomeNote.test.tsx`,
`BudgetStrip.test.tsx`, `ForecastError.test.tsx`, `forecastLoad.test.ts`,
`late.test.ts`, `upcoming.test.ts`.

## Plan (T-24-4)

`services/plan.py` lists the pay cycle (today to the day before payday) so
the month adds up. It adds no rule of its own; every line reads the code
that already owns it:

- **Income**: credits that paid a confirmed income this cycle
  (`income_payments`, the lateness matcher), matched only against the held
  incomes (confirmed before Claude or kept, the lower amount, the label
  before Claude's unkept relabels), so an unkept Claude confirm, raise or
  relabel never lets a credit count (sec on #305); plus incomes still due by
  the eve, held at the lower of now and before Claude. A late income adds nothing.
- **Fixed**: paid, which is this cycle's payments `classify_purchase` calls a
  commitment (in a category with no budget) or a card payoff (card payoffs
  are money out this cycle, as safe to spend counts them); and still to
  pay, which is `money_out_items` (safe to spend's own list: commitments,
  card repayments, planned expenses) over (today, eve], bills held at the
  higher of the two, plus any instalment due earlier this cycle with no
  payment matched to it (a missed match lists it twice: the safe side). Groups by commitment category, plus one group each for
  card repayments and planned items (`source`). A confirmed commitment with
  nothing in the cycle is listed `not_due_this_cycle` and adds nothing.
- **Budgets**: `budget_list`, each with its commitment payments and
  instalments (`coming_up`) and the other purchases. A commitment in a
  budget is never also in Fixed. Each budget counts at
  `max(limit, spent + coming_up)` (its `planned`; they sum to `planned_total`), so moving a commitment
  into a budget never raises Not planned.
- **Not planned** = income − Fixed − `planned_total`.
  `spent_outside_budgets` is `other_spending`.

Lists stop at 50 items per group with the full count. Errors return
"Couldn't load your plan." and log only the exception type. Tests:
`tests/integration/test_plan.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | none. |
| 2 Purge | Inputs are purged; `test_reset_purge.py` calls both routes after a purge. |
| 3 Deletion | Inputs cascade. |
| 4 Demo mode | Both served; sample forecast has no late, per-account breach or budget fields. |
| 5 Ownership | n/a. |
| 6 Scopes | `finance:read`. |
| 7 Claude tools | `cashflow_summary`, `forecast`. |
| 8 Audit | Summary, forecast and projection all honour Claude holds (`counted_commitments`, `held_removed_planned`; T-12-9a, `test_forecast_claude_holds.py`). |
| 9 Bank sync | Computed on read from synced data. |
| 10 Home | Cashflow card (cash, safe to spend, payday, 30-day sparkline, upcoming). Owned by Cashflow. |
| 11 UI routes | `/dashboard`. |
| 12 Tests | listed above. |
| 13 Docs | this file. |
