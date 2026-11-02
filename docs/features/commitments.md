# Commitments (recurring bills and income)

Recurring income and bills, detected from history (at least 3 occurrences,
regular interval, not stale) or added by hand. The user confirms, dismisses,
edits, skips the next one or marks income as payday. Card-repayment
commitments are linked to their card so money counts once. Claude can update
or dismiss commitments; those changes are held until the user keeps them.

## Match keys

Detection groups payments by a key normalised from the description
(`_normalise_merchant`): pure digit runs, dates and tokens with a 6+ digit
reference are dropped; short mixed tokens (`O2`, `MONZO123`) are kept.
Two more rules (T-10-9): the bank's "ON dd MON" date phrase is dropped from
every descriptor, and PayPal's reference glued on with a second `*` is
dropped ("PAYPAL *SPOTIFY*P12A3B4 …" keys as `paypal spotify` every month).
The merchant after `PAYPAL *` always stays, digits and all, so "PAYPAL *O2 UK"
and "PAYPAL *7DIGITAL UK" never merge; other PayPal shapes key as before.
Changing normalisation is a two-part change: `sync_suggestions` heals
detected rules from their label, and `rule_match_keys` (stored key, that key
re-normalised, a PayPal reference stored before T-10-9 healed, label key) is what dedupes detection and matches payments, so
a rule keyed under old rules is never suggested again.

## Which payments are a commitment's (T-19-1)

A merchant can bill one-off purchases under its subscription's descriptor,
so the key alone is not enough. `commitment_matcher` (built once per request
from confirmed rules) matches a transaction when its key matches and its
amount is within max(25%, GBP 5) of some commitment with that key. Rules with
no amount, and rules linked to a holding or loan, match on the key alone (an
overpayment into the holding is not spending). Every consumer uses it: the
transactions list and search (`is_commitment`, `exclude_commitments`), the
Spending lenses, drill-down, trend and money-out composition, budget spend,
and planned-event matching (which also uses the before-Claude version of a
bill while a Claude change to it is unkept; see planned-events.md, T-20-1a). A one-off outside the tolerance counts as
spending; so does a bill that grows past it until its amount is updated. A card-tied
"DD to card" rule is amount-checked too, so with commitments excluded and card
payments shown, a month far off its amount counts in money out (the safe side).
If any rule on a key matches on the key alone, every payment on that key does.

**While a Claude change to a bill is unkept (T-20-1b, owner decision 2).**
`commitment_matcher` is the Spending view: a payment is the bill's only if
the bill as it is now *and* as it was before Claude both take it
(`BothViews`, before-Claude version from `claude_keep.held_match_rules`).
So a Claude cut (GBP 50 to GBP 10 would take GBP 5-15 purchases) or a
Claude confirm of a suggestion can't hide spending from Spending or
budgets, and a raise, dismissal or rename shows the payment as spending at
once. A Claude confirm has no Keep (KP20), so its payments stay spending
until the user undoes it or confirms it by hand (backlog B-26). Planned
matching uses the union instead (`current_commitment_matcher` or the
before-Claude version), so the same payment can be spending here and still
the bill's there: each view is on its own safe side. Incomes are as they are
now in both.

## Linked repayments (T-10-8)

A commitment that carries a liability's repayment (`Liability.linked_commitment_id`)
changes only through the liability. The web `PATCH` and skip,
mark-as-recurring, Claude's `update_commitment` and `dismiss_commitment`
(dry run or not, nothing audited) and undoing an earlier Claude change
return 409 `linked_to_liability` for amount, cadence, interval, next date,
status and `card_account_id` (`services/linked_commitments.py`). Renaming
stays open. A linked repayment is never tied to a card: `link_card_commitments`
skips it (a lender named "American Express" is not an Amex repayment) and
`_card_ties` ignores any stored link, so a card's repayment can never replace
it in safe-to-spend. The list marks such rows `linked_liability: true`.

**Holding links (T-11-3b, ADR-002):** the link set is `commitment_links`
(one row per linked commitment, `UNIQUE(commitment_id)`, owner = an asset
or a liability, server-set `role`, `commitment_created`, `created_on`; FKs
`ON DELETE CASCADE`). Loans write their row beside
`linked_commitment_id`; `linked_commitments()` / `linked_commitment_ids()`
(`services/linked_commitments.py`) read the union, so every guard above
also covers a holding's contribution, which gets 409 `linked_to_holding`
("This payment follows your investment. Change it on Wealth, under
Investments.") and lists as `linked_holding: true`. A bill is linked to at
most one loan or holding (the unique constraint; a race is a 409).
Deleting the holding deletes its row in the same request, so the bill
becomes an ordinary one the user can edit or dismiss (D4).
`sync_suggestions` never suggests an expense with the same amount and
cadence as a linked repayment *and* a payment date within 3 days of it; an
unrelated bill of the same amount on another day is still suggested.

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/analytics/commitments` | `CurrentUserOrMcpRead`; runs `sync_suggestions` first (detection, re-keying, rolling dates), adds late, keep and Claude-marker fields. |
| `POST /api/v1/analytics/commitments` | `CurrentUser` (manual add; T-12-12 bounds: direction and cadence enums, label 1-100 visible characters, amount above £0 to £1,000,000 in pence, intervals bounded, match text up to 200; else 422) |
| `PATCH /api/v1/analytics/commitments/{commitment_id}` | `CurrentUser`; calls `record_user_edit`. Same bounds; status enum; a label is checked only when it changes (bank labels are sent back unchanged). |
| `POST /api/v1/analytics/commitments/{commitment_id}/skip` | `CurrentUser` |
| `POST /api/v1/analytics/commitments/from-transaction` | `CurrentUser` |
| `POST /api/v1/planning/commitments/{commitment_id}/update` | `PlanningWriter` (Claude) |
| `POST /api/v1/planning/commitments/{commitment_id}/dismiss` | `PlanningWriter` (Claude) |

**Tables**: `commitment_rules` (encrypted `label`, `amount`, `match_key`;
plaintext status, cadence, `is_payday`, `card_account_id`,
`skipped_through`, `ends_on`). `ends_on` is the last date a commitment can
fall on (`cadence.commitment_occurrences` stops there); it is set for a
liability's linked repayment ([liabilities.md](liabilities.md)).

**Services**: `services/analytics/commitments.py` (`detect_recurring`,
`sync_suggestions`, `commitment_from_transaction`, `skip_commitment`, payday
helpers), `cadence.py`, `card_links.py`, `late_income.py`,
`services/claude_keep.py`, `services/planning_writes.py`,
`routers/commitment_writes.py`.

**UI**: `/commitments` (`CommitmentsPage`, sub-page off Cashflow),
`AddCommitmentModal`, `EditCommitmentModal`, `UpcomingLabel`,
`changes/KeepControls`, `changes/ClaudeMarker`, "mark recurring" in
`TransactionDetailSheet`; `lib/cadence.ts`, `lib/keep.ts`.

**MCP**: `commitments`, `update_commitment`, `dismiss_commitment`.

**Tests**: `api/tests/unit/test_commitment_dedupe.py`,
`test_paypal_match_key.py`, `test_paypal_commitments.py`, `test_commitment_matcher.py`, `test_spending_claude_hold.py`,
`api/tests/integration/test_linked_commitment_guards.py`, `test_contribution_guards.py`,
`test_commitment_links.py`, `test_commitment_links_migration.py`, `test_card_link.py`,
`test_analytics_service.py`; `api/tests/integration/test_commitment_writes_api.py`,
`test_keep_commitment_api.py`, `test_card_link_api.py`,
`test_claude_payday_dismissal.py`, `test_claude_payday_window.py`,
`test_claude_income_timing.py`, `test_rename_null_match_key.py`,
`test_web_relabel_keeps_match_key.py`, `test_commitment_amount_match.py`; `api/mcp/tests/test_commitment_tools.py`;
UI `KeepControls.test.tsx`, `ClaudeMarker.test.tsx`, `keep.test.ts`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `commitment_rules`; `commitment_links` (migration `c3e5a7b9d1f4`, backfills loan links; downgrade drops it). |
| 2 Purge | Yes; `commitment_links` first (no encrypted column; it references commitments, assets and liabilities). |
| 3 Deletion | Cascade from `users`; disconnecting a bank nulls `account_id`. |
| 4 Demo mode | Served (`commitmentsResponse`). |
| 5 Ownership | Yes for `account_id`, `card_account_id` and the planning update. |
| 6 Scopes | Read `finance:read`; Claude writes `finance:planning.write`. |
| 7 Claude tools | listed above. |
| 8 Audit | Yes, target `commitment`; keep and undo on the Changes page. |
| 9 Bank sync | Suggestions and card links refresh on the next GET, not during sync. |
| 10 Home | "N recurring payments detected" banner and upcoming items. Owned by Cashflow. |
| 11 UI routes | `/commitments`. |
| 12 Tests | listed above; no `CommitmentsPage` UI test. |
| 13 Docs | `api/mcp/README.md` (stale, see gaps). |
