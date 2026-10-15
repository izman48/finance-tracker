# Budgets

A whole-pound limit per spending category, per pay cycle. Budgets track
purchases only and never change safe to spend or any other money figure. Up
to 20 per user, one active budget per category. Users get suggestions
(median of the last 3 cycles, rounded up to £10), a history of past cycles,
nudges when a budget is at risk, and a budget line on the forecast. Claude can
set, pause, resume and remove budgets.

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
(the one counting rule, `classify_purchase`: excludes commitments,
transfers, card payoffs, financed purchases), `services/budget_history.py`,
`api/app/schemas/budgets.py`.

**UI**: Spending tab, `?section=budgets` (`components/budgets/BudgetsPanel`,
`BudgetsView`, `BudgetsSegment`, `HistoryView`, `HistoryBars`,
`ManageSheet`, `ManageModes`, `SuggestSheet`), Home budget line
(`OverviewPage`), `forecast/BudgetStrip` and `ForecastChart` on Cashflow,
`NudgeFeed`. `lib/budgets.ts`, `lib/budgetHistory.ts`,
`lib/budgetProjection.ts`, `lib/budgets.fixtures.ts`.

**MCP**: `list_budgets`, `set_budgets`, `pause_budget`, `resume_budget`,
`remove_budget`.

**Tests**: `api/tests/integration/test_budgets_api.py`,
`test_budget_spend.py`, `test_budget_history.py`,
`test_budget_projection.py`, `test_budget_invariance.py`,
`test_budget_home_nudges.py`, `test_budgets_consent.py`,
`test_budget_writes_api.py`; `api/mcp/tests/test_budget_tools.py`; UI tests
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
