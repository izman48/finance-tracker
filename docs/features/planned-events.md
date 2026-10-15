# Planned events (one-offs and instalment plans)

User-entered future money movements (one-off, recurring, instalment plan)
that feed the forecast, safe to spend and the net-worth projection. A
one-off is settled automatically by a matching transaction (±7 days, exact
amount or ±max(£1, 2%) with a shared word). "Pay on finance" turns a purchase
into an instalment plan and drops the lump from spending. Claude can add
one-offs and soft-remove the ones it created; a removed expense keeps
counting until the user keeps the change.

**Card payments (T-12-4a, owner 2026-10-15, card-agnostic)**: a planned
item can be marked `is_card_payment` (a plain flag on create or PATCH; no
card is chosen and nothing is matched by name). In each pay window (cut at
paydays) the summary's safe-to-spend window, savable and the Cashflow
forecast count the larger of the flagged planned card payments and the
projected card repayments of all cards, never both and never a subtraction
(`services/analytics/card_payments.py`). A window with only one side keeps
it. Claude's `add_planned_event` can't set the flag (key-set test). The
Wealth projection is unchanged: a flagged item still counts there.
The overlap is shown (T-12-4b): `GET /api/v1/analytics/planned-items`
marks a flagged item `card_payment_overlap` while it falls in a pay window
(today to 92 days ahead, read with the summary's inputs, Claude holds
included) with projected card bills, and `GET /api/v1/analytics/nudges`
adds `card_payment_overlap_{payday anchor}` (the day before payday for the
current window, so a dismissal lasts it) with the aggregate figures ("Your
planned card payments (£X) overlap your projected card bills (£Y). nilu
counts the larger, £Z, once."), dismissed in the browser like the other
non-budget nudges.

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/analytics/planned-items` | `CurrentUser` |
| `POST /api/v1/analytics/planned-items` | `CurrentUser` |
| `PATCH /api/v1/analytics/planned-items/{item_id}` | `CurrentUser` (only `is_card_payment`, `extra="forbid"`; T-12-4a) |
| `DELETE /api/v1/analytics/planned-items/{item_id}` | `CurrentUser` (hard delete) |
| `POST /api/v1/analytics/planned/from-transaction` | `CurrentUser` (pay on finance) |
| `GET /api/v1/planning/planned-events` | `CurrentUserOrMcpRead` (limit 200) |
| `POST /api/v1/planning/planned-events` | `PlanningWriter` (dry run, idempotency, 24 h duplicate guard) |
| `POST /api/v1/planning/planned-events/{item_id}/remove` | `PlanningWriter` (soft remove) |

**Tables**: `planned_items` (encrypted `name`, `amount`, `total_amount`,
`apr`, `fee_amount`; `source_transaction_id` set null on delete;
`created_via` web or mcp).

**Services**: `services/analytics/planned.py`, `planned_matching.py`,
`commitments.convert_transaction_to_plan`,
`spending.financed_transaction_ids`, `services/claude_keep.py`,
`routers/planning.py`.

**UI**: `PlannedItems` (on `/commitments`), `AddCommitmentModal`,
`PayOnFinanceModal` (on `/insights`), `lib/planned.ts`. The UI never calls
`/planning/*`.

**MCP**: `list_planned_events`, `add_planned_event`, `remove_planned_event`.

**Tests**: `api/tests/integration/test_planned_events_api.py`,
`test_planned_matching.py`, `test_planned_removal_hold.py`,
`test_planning_writes.py`, `test_planning_write_auth.py`;
`api/mcp/tests/test_planned_events_tools.py`; UI `PlannedItems.test.tsx`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `planned_items`. |
| 2 Purge | Yes. |
| 3 Deletion | Cascade from `users`. |
| 4 Demo mode | `/analytics/planned-items` served (one sample item). |
| 5 Ownership | Yes (`account_id` on both POSTs). |
| 6 Scopes | Read `finance:read`; Claude writes `finance:planning.write`. |
| 7 Claude tools | listed above. |
| 8 Audit | Yes, target `planned_event`. The web DELETE hard-deletes even Claude's items, which breaks their undo (gap). |
| 9 Bank sync | Matching runs on read. |
| 10 Home | Upcoming items on the Cashflow card. Owned by Cashflow. |
| 11 UI routes | `/commitments`. |
| 12 Tests | listed above. |
| 13 Docs | this file. |
