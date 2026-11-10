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
Services, UI and Demo (eng-b). Nothing reads marks yet.

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

## Routes

None yet.

## Scopes

None yet.

## Audit

None yet.

## MCP

None yet.

## Figures

None yet.

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
| 5 Ownership | No account ids. |
| 6 Scopes | None yet. |
| 7 Claude tools | None yet. |
| 8 Audit | None yet. |
| 9 Bank sync | A sync never changes marks. A transaction removed with its connection removes its marks. |
| 10 Home | n/a. |
| 11 UI routes | None. |
| 12 Tests | listed above. |
| 13 Docs | This file, `data-lifecycle.md` (purge order). |
