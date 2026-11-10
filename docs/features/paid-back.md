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

## Routes

None yet.

## Scopes

None yet.

## Audit

Target `repayment_mark` in `services/planning_writes.TARGETS`, label
`label`, allow-listed fields `amount`, `spend_transaction_id`, `category`,
`active`. Undoing a mark soft-deletes it; a second undo is a no-op. Undoing
an unmark re-activates the mark only if its credit and spend still have room
(T-03-2 T6), else 409 "Can't undo: it has changed since."

## MCP

None yet.

## Figures

Budgets (T-03-4 P2, `services/budget_spend.py`; PRD ACs 1, 2, 4 to 7, 29, 30):

- A mark on a spend nets that spend in its own cycle, and only while the
  spend still counts as card or cash spending. A spend later set to a
  transfer or card payoff nets nothing; setting it back restores the net.
- A mark on a category nets that category in the cycle its credit arrived
  (UTC day, as the transaction window), never below £0. Unbudgeted and
  paused categories net under "Other spending".
- Tracking, pace, `left`, nudges, snapshots, suggest and the dotted line
  inherit the net. `budgetable_categories` and `commitment_covered` read
  `gross_by_category`, so a mark never changes which categories may have a
  budget (T-03-2 T5).
- `budget_spend(..., extra_marks=[...])` nets unsaved marks for previews
  (T7). No money figure moves (`test_budget_invariance.py`, "paid-back marks").

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

None yet.

## UI

None yet.

## Demo

None yet.

## Tests

`api/tests/integration/test_repayment_marks.py`; `test_reset_purge.py` and
`test_delete_account.py` seed a mark; `tests/unit/test_privacy_plaintext.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `repayment_marks`, additive migration with downgrade. |
| 2 Purge | Yes, first in `_OWNED_BY_USER`, before transactions (seeded in the reset test). |
| 3 Deletion | Cascade from `users`, and from either transaction. |
| 4 Demo mode | Nothing shown yet. |
| 5 Ownership | No account ids. Reads join transactions to the user's accounts. |
| 6 Scopes | None yet. |
| 7 Claude tools | None yet. |
| 8 Audit | Yes, target `repayment_mark` (above). |
| 9 Bank sync | A sync never changes marks. A transaction removed with its connection removes its marks. |
| 10 Home | n/a. |
| 11 UI routes | None. |
| 12 Tests | listed above. |
| 13 Docs | This file, `data-lifecycle.md` (purge order), `claude-changes.md` (targets). |
