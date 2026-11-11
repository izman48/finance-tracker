# Paid back (repayment marks)

Friends pay you back for a shared bill. A **repayment mark** says "this much
of an incoming payment paid back a spend" (netted in the spend's cycle) or,
with no spend, "paid back a category" (netted in the cycle the payment
arrived). Budgets and the Spending purchases view then show what you really
spent. A mark never makes a payment income and never moves money out of the
bank, safe to spend, savable or the forecast balance line. Spec: the T-03-1
PRD (hybrid, Claude first) and its T-03-2 feasibility section.

Built in stages on `feat/paid-back`. Sections are owned per engineer
(T-03-2 T15): Tables, Routes, Scopes, Audit and MCP (eng-a); Figures,
Services, UI and Demo (eng-b). No figure reads marks yet.

## Tables

`repayment_marks` (migration `3c6965e7da5d`, downgrade drops it):

- `credit_transaction_id` (required), and exactly one of
  `spend_transaction_id` or `category` (check `ck_repayment_marks_one_target`).
- `amount` and `label` are DEK-encrypted. `category`, `active`,
  `created_via` (`mcp` or `web`) and the dates are plain, listed in
  `api/app/core/privacy_plaintext.py`.
- `active` false is an unmark (soft delete), so Claude's changes keep their
  history and undo works.
- One active mark per credit and spend, and per credit and category
  (partial unique indexes). `user_id`, the credit and the spend all
  cascade: a bank disconnect or account deletion takes the marks with it.

**Read service** (`api/app/services/repayment_marks.py`). Amounts are
encrypted, so caps are applied in Python. `active_marks`: the user's active
marks, oldest first, each clamped so a credit is never marked past its
amount and a spend never netted past its own (`applied_amount` vs
`recorded`). `extra=` nets unsaved proposed marks after them, for previews.
`remaining`: what is left unmarked on each of the user's transactions.
`fits`: a proposed mark against both caps. `lock_user_marks` (the user row,
FOR UPDATE) serialises writes; take it before any mark row (undo does). Other users' transactions are never read; a
mark naming one applies nothing.

## Income guards (eng-a)

A marked credit is never income (PRD decision 3): recurring-income
detection (`analytics/commitments.detect_recurring`), planned-income
settling (`analytics/planned_matching`) and late-income clearing
(`analytics/late_income`) all skip credits with an active mark
(`repayment_marks.marked_credit_ids`). An unmarked credit behaves as before.
So a confirmed income paid only by a marked credit shows as late, and a
suggested income from that payer can fade. Money figures don't move.

`services/repayment_guards.py`, for the write routes and candidates:

- `income_locked_credit_ids`: credits that settle a planned income item
  (`planned_income`) or pay a confirmed income's latest payment, late or
  still inside its grace days (`late_income`). Marking them is refused.
- `income_commitment_payers`: credits whose payer (`late_income.payer_words`)
  has a suggested or confirmed income commitment. Marking them needs
  `accept_warnings`.

Undoing an unmark is refused (409) when the credit is now locked, as well
as when the caps have no room.

## Routes

Claude's writes (`api/app/routers/repayment_writes.py`, all
`RepaymentsWriter`, dry run by default, idempotency key, audited):

| Route | Notes |
|---|---|
| `POST /api/v1/planning/repayments/mark` | 1 to 8 marks (`credit_id`, exactly one of `spend_id` or `category`, optional `amount_pounds`), all saved or none, one audit row each with a shared `batch_id`. Every check runs first, under `lock_user_marks` (`services/repayment_writes.plan_marks`): both payments the user's (else 404 "Not found"), a credit and a purchase that budgets count (not a transfer, card payoff, financed or commitment), a known category, the caps across the whole call, the income block (`repayment_guards`), and the payer warning (refused on apply until `accept_warnings`). The amount defaults to the smaller room. An identical repeat is `unchanged`; the same pair with another amount is 422 "Already marked …". The response adds `marks`: per entry the amount, warnings, `cycle` (`start`, `end`, `closed`), `spend_before`/`spend_after`, `category_spent_before`/`after`, `budget_left_before`/`after` (null with no active budget; negative means over, and the sentence says "£n over £limit") and an `effect` sentence. "After" is after every mark in the call, by `budget_spend(extra_marks=)` (T7); figures are computed before the write, for a preview and an apply alike. A replay returns the stored audit rows only (T4). |
| `POST /api/v1/planning/repayments/{mark_id}/unmark` | Soft-deletes one active mark Claude made (`created_via == "mcp"`). Any other id, another user's included, is 404 "Not found". Takes `lock_user_marks` first. A retry of an applied unmark replays. |

Read: `POST /api/v1/repayments/candidates` (`routers/repayments.py`, `CurrentUserOrMcpRead`,
read only despite POST so the payer hint stays out of access logs, as search does):
the PRD's `list_repayment_candidates` over `services/repayment_candidates`.
Body `payer`, `about` (≤ 100 visible characters), `spend_date`, `frm`, `to` (at most
366 days, `frm` ≤ `to`), `include_marked`, `limit` (1 to 50); unknown keys 422.
Rate limited per user (`repayment-candidates`, 30 a minute).

Reads: `GET /api/v1/banking/transactions` and `POST /api/v1/banking/transactions/search`
(`services/repayment_views.paid_back_view`, T-03-3 P6) give each debit
`paid_back_amount` (what its marks net now) and both payments
`paid_back_marks`: `mark_id`, `credit_id`, `spend_id` or `category`,
`amount` (after the caps), `label`, `created_via`, `applied` (false when the
spend no longer counts as spending, AC-29), `cycle_closed` (it nets in a
cycle before the current one) and `audit_id` (Claude's change, for Undo;
null for a mark made in the app), plus `payer`, `against` (the spend's name or the category), `credit_date` and `spend_date` for the sheet's rows. Search's `total_amount` stays the bank total.

## Scopes

`finance:repayments.write` (T-03-2 T1): its own unticked consent box, "Mark
payments as paid back", whose copy names the power. No other write scope
implies it and existing grants never gain it, so the owner reconnects
Claude once. Web sessions may call the routes too. Rate limits are shared
with every write (30 writes, 120 dry runs an hour).

## Audit

Target `repayment_mark` in `services/planning_writes.TARGETS`, label
`label`, allow-listed fields `amount`, `spend_transaction_id`, `category`,
`active`. Undoing a mark soft-deletes it; a second undo is a no-op. Undoing
an unmark re-activates the mark only if its credit and spend still have room
(T-03-2 T6), else 409 "Can't undo: it has changed since."

## MCP

`api/mcp/server.py` (T-03-5 P9): `list_repayment_candidates` (read),
`mark_paid_back` and `unmark_paid_back` (`write_tool(destructive=True)`,
`dry_run` by default, each checks `finance:repayments.write` first and
names the power when it is missing: "This connection wasn't granted
permission to mark payments as paid back. Reconnect and approve it.").
Every id is parsed as a UUID before it reaches a URL or body; a mark entry
may carry only `credit_id`, `spend_id`, `category` and `amount_pounds` (a
decimal string). API errors become the PRD's sentences: 404 "Not found: no
payment of yours has that id." / "… no active mark of yours that Claude
made has that id.", 422 details pass through, 5xx "The change failed (500)."
A replayed mark returns `results` without figures. Tests:
`api/mcp/tests/test_repayment_tools.py`, `test_tool_annotations.py`.

## Figures

Budgets (T-03-4 P2, `services/budget_spend.py`; PRD ACs 1, 2, 4 to 7, 29, 30):

- A mark on a spend nets that spend in its own cycle, and only while the
  spend still counts as card or cash spending. A spend later set to a
  transfer or card payoff nets nothing; setting it back restores the net.
- A mark on a category nets that category in the cycle its credit arrived
  (UTC day, as the transaction window), never below £0. Unbudgeted and
  paused categories net under "Other spending".
- `GET /api/v1/budgets` `not_counted` gains `paid_back` (every mark netted this
  cycle, excess included), `paid_back_marks` (label, amount, `against`: the
  spend's name or the category) and `paid_back_excess` (by category: shown,
  never income).
- Tracking, pace, `left`, nudges, snapshots, suggest and the dotted line
  inherit the net. `budgetable_categories` and `commitment_covered` read
  `gross_by_category`, so a mark never changes which categories may have a
  budget (T-03-2 T5).
- `budget_spend(..., extra_marks=[...])` nets unsaved marks for previews
  (T7). No money figure moves (`test_budget_invariance.py`, "paid-back marks").

History and Cashflow (T-03-6 P11a; AC-3, decision 6, T-03-2 T17):

- A closed cycle's snapshot is never rewritten. A mark made before the
  snapshot is first written (snapshots are lazy) is in it. Each History cycle
  has `paid_back_after_close`: marks netted in that cycle, against one of its
  budgeted categories, made after its snapshot ("£40.00 more paid back after
  this cycle closed"). Snapshots now take `written_at` from the app's clock,
  as marks take `created_at`.
- `budget_projection.left_raised_by_marks`: how much marks raised `left`
  this cycle (excess and unbudgeted marks move nothing), so the chart says
  why the dotted line sits lower only when it does.

Spending (T-03-4 P3, `services/analytics/spending.py`; ACs 3, 8, 32):

- Purchases lens: a spend mark nets the spend in its own kind (card or
  cash), category and merchant. Category marks net per category for the
  range shown, floored at £0, only with no `account_id` or `kind` filter
  (T8). `total_spent` = card + cash − `paid_back_by_others`; each category
  has `paid_back_by_others` (the drill's reference row);
  `paid_back_excess` lists the rest.
- `/spending/transactions` rows gain `paid_back` and `counted`.
- Trend: spend marks in the spend's month, category marks in the credit's
  month floored per category and month; rows gain `paid_back_by_others`.
  Wealth's average spending reads this trend, so marked months read lower.
- The money-out lens never reads marks (T9). Near the £0 floor, a cycle, a
  date range and a month can differ (PRD Risks).

## Services

- `services/paid_back.py`: the netting rule shared by budgets and Spending
  (see Figures).
- `services/repayment_candidates.py` (T-03-5 P7; PRD "Which spend is most
  likely", ACs 9 to 14): `repayment_candidates(db, user, today=..., payer,
  about, spend_date, frm, to, include_marked, limit)` lists the user's
  credits in the range (default 45 days, at most 366), newest first, at most
  50. A credit is listed while part of it is unmarked, whether or not it is
  typed as a transfer. Each comes with `blocked` and `warnings` from
  `repayment_guards`, its `likely_spend` (score 45 or more), up to 2
  `alternatives` (30 or more), and a `fallback_category` when nothing
  reaches 45. A spend is eligible if budgets count it, it falls 21 days
  before to 3 days after the credit, and its unmarked room covers the credit
  less max(£1, 2%). Scores are computed per request and never stored. P8
  serves them on a read route.

## UI

- Budgets, Not counted (`components/budgets/PaidBackByOthers.tsx`, T-03-6
  P11b): "Paid back by others £110.00", only above £0, as a toggle button
  (`aria-expanded`) listing each mark's label, what it netted and its amount,
  with the helper "Friends' repayments you marked. They reduce what counts as
  spending here and are never income." Excess: "£40.00 was more than you
  spent in Eating out this cycle. It isn't income."
- History (`HistoryView`): "{cycle}: £40.00 more paid back after this cycle
  closed" under the bars; the result is unchanged.
- Cashflow (`forecast/BudgetStrip`): when `paid_back_this_cycle` is above £0,
  "Marking a repayment raises what is left in a budget, so this line is
  lower. The cash itself is already in your balance."

## Demo

The sample account (`ui/src/lib/sampleAccount.ts`, T-03-6 P10c; AC-33,
owner rule 2026-10-15) has the PRD's example in this pay cycle: a £200
Harbour Pizzeria dinner on the card, S PATEL £60 and J OKAFOR £50 marked
against it by Claude (`SAMPLE_MARKS`). The transactions carry
`paid_back_amount` and `paid_back_marks`; the purchases lens and budgets net
the dinner to £90 (the sample's Eating out budget is £150, as in the PRD);
budgets list both under "Paid back by others"; the forecast's
`left_raised_by_marks` is set; `/audit` lists the two marks, so "Changes made
by Claude" shows them. Undo is a write, so demo mode blocks it like any other.

## Tests

`api/tests/integration/test_repayment_marks.py`; `test_reset_purge.py` and
`test_delete_account.py` seed a mark; `tests/unit/test_privacy_plaintext.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `repayment_marks`, additive migration with downgrade. |
| 2 Purge | Yes, first in `_OWNED_BY_USER`, before transactions (seeded in the reset test). |
| 3 Deletion | Cascade from `users`, and from either transaction. |
| 4 Demo mode | Yes: the sample dinner and its two marks (see Demo). |
| 5 Ownership | No account ids. Reads join transactions to the user's accounts. |
| 6 Scopes | Claude's writes `finance:repayments.write` (own consent box). |
| 7 Claude tools | `list_repayment_candidates`, `mark_paid_back`, `unmark_paid_back`. |
| 8 Audit | Yes, target `repayment_mark` (above). |
| 9 Bank sync | A sync never changes marks. A transaction removed with its connection removes its marks. |
| 10 Home | n/a. |
| 11 UI routes | None. |
| 12 Tests | listed above. |
| 13 Docs | This file, `data-lifecycle.md` (purge order), `claude-changes.md` (targets). |
