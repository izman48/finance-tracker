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
`sync_suggestions` never suggests an expense with the same amount and
cadence as a linked repayment *and* a payment date within 3 days of it; an
unrelated bill of the same amount on another day is still suggested.

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/analytics/commitments` | `CurrentUserOrMcpRead`; runs `sync_suggestions` first (detection, re-keying, rolling dates), adds late, keep and Claude-marker fields. |
| `POST /api/v1/analytics/commitments` | `CurrentUser` (manual add) |
| `PATCH /api/v1/analytics/commitments/{commitment_id}` | `CurrentUser`; calls `record_user_edit`. |
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
`test_paypal_match_key.py`, `test_paypal_commitments.py`,
`api/tests/integration/test_linked_commitment_guards.py`, `test_card_link.py`,
`test_analytics_service.py`; `api/tests/integration/test_commitment_writes_api.py`,
`test_keep_commitment_api.py`, `test_card_link_api.py`,
`test_claude_payday_dismissal.py`, `test_claude_payday_window.py`,
`test_claude_income_timing.py`, `test_rename_null_match_key.py`,
`test_web_relabel_keeps_match_key.py`; `api/mcp/tests/test_commitment_tools.py`;
UI `KeepControls.test.tsx`, `ClaudeMarker.test.tsx`, `keep.test.ts`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `commitment_rules`. |
| 2 Purge | Yes. |
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
