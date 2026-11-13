# Budgets

A whole-pound limit per spending category, per pay cycle. Budgets track
purchases and, once paid, the payments of commitments in a budgeted
category; they never change safe to spend or any other money figure. Up
to 20 per user, one active budget per category. Users get suggestions
(median of the last 3 cycles, rounded up to £10), a history of past cycles,
nudges when a budget is at risk, and a budget line on the forecast. Claude can
set, pause, resume and remove budgets.

## Commitments inside a budget (T-24-3a)

Owner, 2026-11-13: a commitment counts inside its budget category, only when
paid. A payment `classify_purchase` calls a commitment counts in `spent`
when its own category (exact text) has an active, unpaused budget;
otherwise it stays under "Not counted here" (`not_counted.commitments`, or
`commitments_no_category` for a payment with no category). Any category can
have a budget now, rent and bills included (the Sprint 09 "mostly
commitments" block is lifted for the web and `set_budgets`; suggestions
still leave such categories out, and measure every other category as its
budget would count it, paid commitments included, so Suggest and Past
cycles agree).

Each budget row also has `coming_up`: the commitment instalments due after
today and by the cycle's last day, taken from `held_scheduled_outflows`
(`services/analytics/forecast.py`), the same held view the forecast
schedules, so Claude's pending cut or dismissal never lowers it and a
card-tied bill the forecast drops is not in it. An instalment goes to its
commitment's category (`services/commitment_category.py`). A £0 rule or one
linked to a loan or holding adds nothing. `coming_up` never changes `spent`,
`over_by` or `status`; `over_by_payday = max(0, spent + coming_up − limit)`.
`status` is `budget_used` when spent equals the limit. Pace (lead,
2026-11-13; sec on #298): `pace_spent = placed + max(0, limit − placed) ×
share of the cycle gone`; coming up plays no part, so an instalment that is
only due never moves the status. Placed commitment payments sit on the
line at their real dates and only the flexible rest is spread, so rent paid
on day 1 isn't "ahead of pace". `services/budget_pace.py` caps what each
commitment places at its amount × instalments due so far this cycle (a
one-off under a subscription's descriptor is spread like any purchase),
judges an unkept Claude change by the smaller of now and before-Claude
(confirmed in both, lower amount, fewer instalments, the old match keys),
and never places more than the budget's spent. With no commitments it is
the even spread. Status, the pace tick and the pace nudge all read this one figure. Items are at most 5,
earliest first; `amount`, `commitment_count` and `instalment_count` cover
all of them. A closed cycle's stored snapshot is never rewritten; a cycle
first loaded after this change is written under the new rule.

### The dotted line with commitments (T-24-3b)

A budgeted category's instalments are already on the forecast's solid line,
so `budget_projection` subtracts, per budget, only what they leave of the
limit: this cycle `max(0, limit − spent − instalments due by the day before
payday)`, each later cycle `max(0, limit − that cycle's instalments)`. Each
budget on its own, so one budget's instalments never free another's limit.
The instalments come from `held_scheduled_outflows` over the same window as
the forecast the line is drawn on (`budgeted_instalments`, the filter
`coming_up` uses), not from `coming_up`, whose held view is judged over this
cycle only: a pending Claude change can't lift the line at any payday eve
(tested). Instalments past the horizon are unknown, so a cycle the horizon
cuts subtracts more, never less.

**Demo (T-24-5b):** `sampleBudgets.ts` mirrors the counting, coming-up,
pace and dotted-line rules. A sample Subscriptions budget (£20) holds the
sample's two subscriptions. They're due before payday, so demo shows the
"will go over" bar. They come from `SCHEDULED_BILLS` in `sampleAccount.ts`,
the same list the demo forecast schedules, so coming up never holds an
instalment the demo forecast doesn't.

## Code

**API**, web (`api/app/routers/budgets.py`):

| Route | Auth | Notes |
|---|---|---|
| `GET /api/v1/budgets` | `CurrentUserOrMcpRead` | `?include=categories` adds the categories a new budget may use. Writes missing cycle snapshots first. |
| `GET /api/v1/budgets/history` | `CurrentUser` | `cycles` 1–12, optional `before`. |
| `POST /api/v1/budgets` | `CurrentUser` | create |
| `PUT /api/v1/budgets` | `CurrentUser` | bulk upsert, all or nothing |
| `PATCH /api/v1/budgets/{budget_id}` | `CurrentUser` | `limit_pounds` and/or `paused` |
| `DELETE /api/v1/budgets/{budget_id}` | `CurrentUser` | soft delete (`active=False`) |
| `POST /api/v1/budgets/suggest` | `CurrentUser` | read-only despite POST, so it is blocked in demo mode |
| `POST /api/v1/budgets/nudges/{nudge_id}/dismiss` | `CurrentUser` | |

**API**, Claude (`api/app/routers/budget_writes.py`, all `BudgetsWriter`,
`finance:budgets.write`, dry run by default):

- `POST /api/v1/planning/budgets/set` (up to 8 entries, `run_batch`, one
  audit row per changed budget)
- `POST /api/v1/planning/budgets/{budget_id}/pause`
- `POST /api/v1/planning/budgets/{budget_id}/resume`
- `POST /api/v1/planning/budgets/{budget_id}/remove`

**Tables**: `budgets` (encrypted `limit_pounds`, `held_remaining`; the
`held_*` columns are unused since T-09-14 but still purged),
`budget_nudges` (no encrypted columns), `budget_changes` (append-only log),
`budget_cycle_snapshots` (encrypted `limit_pounds`, `spent`).

**Services**: `services/budgets.py` (cycles, cap, `budget_list`,
`budget_projection`, `budget_nudges`, `suggest`), `services/budget_spend.py`
(the one counting rule, `classify_purchase`: excludes commitments outside
a budgeted category, transfers, card payoffs, financed purchases; nets
paid-back marks, see
[paid-back.md](paid-back.md) "Figures"), `services/budget_coming_up.py`,
`services/budget_history.py`,
`api/app/schemas/budgets.py`.

**UI**: Spending tab, `?section=budgets` (`components/budgets/BudgetsPanel`,
`BudgetsView`, `BudgetsSegment`, `HistoryView`, `HistoryBars`,
`ManageSheet`, `ManageModes`, `SuggestSheet`, `PaidBackByOthers`), Home budget line
(`OverviewPage`), `forecast/BudgetStrip` and `ForecastChart` on Cashflow,
`NudgeFeed`. `lib/budgets.ts`, `lib/budgetBar.ts` (the bar with coming up: widths only, every figure the API's), `lib/budgetHistory.ts`,
`lib/budgetProjection.ts`, `lib/budgets.fixtures.ts`.
`BudgetsPanel` also reads `GET /api/v1/plan` (T-25-3; fail-soft, the page shows
without it): each budget with commitment payments says "Includes Foodery
£129.74" (`lib/plan.budgetIncludes`), and when no budget, paused or not, is
for Subscriptions, a Subscriptions card lists Plan's Subscriptions group,
each paid or coming, with its total and no limit or pace
(`subscriptionsWithoutBudget`).

**MCP**: `list_budgets`, `set_budgets`, `pause_budget`, `resume_budget`,
`remove_budget`.

**Tests**: `api/tests/integration/test_budgets_api.py`,
`test_budget_spend.py`, `test_budget_history.py`,
`test_budget_projection.py`, `test_budget_invariance.py`, `test_budget_paid_back.py`,
`test_budget_home_nudges.py`, `test_budgets_consent.py`,
`test_budget_writes_api.py`, `test_budget_commitments.py`; `api/mcp/tests/test_budget_tools.py`; UI tests
next to every component and lib file above.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `budgets`, `budget_nudges`, `budget_changes`, `budget_cycle_snapshots`. |
| 2 Purge | Yes, all four. |
| 3 Deletion | Cascade from `users`. |
| 4 Demo mode | Served (T-11-8): `GET /api/v1/budgets` and `GET /api/v1/budgets/history` come from `ui/src/lib/sampleBudgets.ts`, computed from the sample ledger with the API's rules (purchases per category in the pay cycle, pace, kept), so they reconcile with Spending (`sampleBudgets.test.tsx`). The projection's "My budgets" uses their total. The sample forecast has `budget_projection` (the dotted line and payday strip on every horizon) and the sample nudges have budget nudges, both by the API's rules (`sampleBudgetProjection`, `sampleBudgetNudges`; `sampleBudgetLine.test.ts`, T-11-10). |
| 5 Ownership | n/a (no account ids); budget ids are owner-checked. |
| 6 Scopes | List `finance:read`; Claude writes `finance:budgets.write`; everything else web only. |
| 7 Claude tools | listed above. |
| 8 Audit | Yes, target `budget` (`limit_pounds`, `paused`, `active`). Budget changes take effect at once: no keep state. |
| 9 Bank sync | Spend is computed on read from synced transactions. |
| 10 Home | "X of Y on pace" on the Spending card; budget line on the Cashflow forecast. Owned by Spending. |
| Wealth projection | The Wealth projection (`spending_source=budgets` on `GET /api/v1/analytics/net-worth-projection`) uses the total of active, unpaused limits (`cycle_budgets(...).total_limit`, the Cashflow budget line's figure) as monthly spending; £0 falls back to the average (T-10-15b). Read-only. |
| 11 UI routes | `/insights` (`?section=budgets`). |
| 12 Tests | listed above. |
| 13 Docs | `api/mcp/README.md` doesn't list the budget tools yet (gap). |
