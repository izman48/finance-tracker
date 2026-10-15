# Accounts, roles and card repayments

Lists connected accounts with balances and freshness. The user sets each
account's cashflow role (spending, savings, credit, excluded), overdraft and,
for credit cards, how the balance is repaid. Money owed on cards is shown
with one sign whatever the provider. Each card can hold its statements
(balance, statement date, due date, optional minimum), from which the API
derives the amount still due and the spend since the statement (unbilled).

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/banking/accounts` | `CurrentUserOrMcpRead`; adds `credit_owed`, `last_synced_at`, `sync_stale`. |
| `PATCH /api/v1/analytics/accounts/{account_id}/settings` | `CurrentUser`; role, overdraft, repayment config, `pay_from_account_id`, `instalment_card`, `card_apr` (0-100, encrypted, credit only). Returns `warnings` (see below). Role, strategy and cadence are enums (422). Repayment fields only on a credit account (the role after the patch). `scheduled` only on a card marked `instalment_card`; a card already on it can still be edited, but switching to it or unmarking the card is 422. |
| `GET /api/v1/analytics/accounts/{account_id}/repayments` | `CurrentUser` |
| `POST /api/v1/analytics/accounts/{account_id}/repayments` | `CurrentUser` |
| `DELETE /api/v1/analytics/accounts/{account_id}/repayments/{item_id}` | `CurrentUser` |
| `GET /api/v1/analytics/accounts/{account_id}/statements` | `CurrentUser`; newest 24 statements plus `current` (amount still due, unbilled, paid), `missing_statement` (the current one's due date has passed), `warnings` and `card_apr` and `next_payment` (amount, date, pay-from account name, from `repayment_events`; null while a commitment is tied to the card (which of the two the forecast counts depends on its window), so it never disagrees with the forecast), derived on read. |
| `POST /api/v1/analytics/accounts/{account_id}/statements` | `CurrentUser`; manual statement, credit accounts only (else 422); same card and date twice is 409. |
| `PATCH /api/v1/analytics/accounts/{account_id}/statements/{statement_id}` | `CurrentUser`; on a provider statement it saves the user's own (manual) one for that period and returns that row (a different `id`: reload the list). |
| `DELETE /api/v1/analytics/accounts/{account_id}/statements/{statement_id}` | `CurrentUser`; the card goes back to its current balance. A provider statement is 409 (sync would bring it back). |
| `PUT /api/v1/analytics/accounts/{account_id}/statements/{statement_id}/in-use` | `CurrentUser`; use this statement for its period (no body). Choosing the provider's removes the manual one for that period. |

**Tables**: `accounts` (encrypted names and balances; plaintext
`external_id`, `account_type`, `currency`), `account_settings` (kept apart
from `accounts` so sync never overwrites them), `repayment_schedule_items`
(encrypted `amount`), `card_statements` (encrypted `statement_balance`,
`minimum_due`; plaintext dates and `source` = `manual` or `provider`; unique
per card, statement date and source).

**Services**: `services/balance_sign.py` (`credit_owed`: the only way to read
money owed; unverified providers fall back to `abs()`),
`services/analytics/common.py` (`default_role`, `resolve_roles`),
`services/analytics/repayments.py` (strategies `full_balance`, `fixed`,
`installments`, `minimum_percent`, `scheduled`, `statement_balance`; an
unknown strategy pays the full balance; pay day is a cadence or
`card_due_date`; a card repayment and its linked commitment count once), `services/analytics/card_links.py`,
`services/analytics/statements.py` (current statement, amount still due,
unbilled; only credits identified as payments reduce the amount due, and
nothing naming a refund or reversal counts, so the full statement stays due:
fail-safe). Statement dates are at most 400 days old and never in the future.

**`statement_balance`** (opt-in; existing strategies are unchanged): the amount
still due goes on the statement's pay day and the unbilled spend on the next
one, so the total never falls below the full balance. With no statement, or
once the current one's due date has passed with no newer one, the full
current balance goes on the next pay day. Each repayment says what it is
(T-12-7a): `projected` and `parts` (summed to the amount by the API). The
still-due amount is a real bill (`statement`, not projected); the unbilled
spend (`spent_since`) and the no-statement balance (`balance`) are
projected. Other strategies send `projected: false` and no parts. Coming
up reads "{card} bill" or "{card} bill (projected)", and Cashflow adds
line 2 ("Spent since £X" / "Balance £X"); card plan instalments stay
their own rows. **Pay day `card_due_date`** (any
formula strategy; the default when `statement_balance` has no cadence): the
current statement's due date, then monthly, rolled forward past dates
already gone; with no statement, the card's `repayment_day`, else 30 days
from today. Summary, forecast and projections all read these through
`repayment_events` / `scheduled_outflows`.

**Warnings** (`services/analytics/repayment_warnings.py`, T-10-5): codes plus string values,
worded by the UI, about the card's next repayment as the forecast plans it: `interest_cost`
(the payment is less than what is still due on the statement; with `card_apr` the monthly
estimate is the unpaid part times (1 + APR)^(1/12) − 1, otherwise no figure), `late_fee_risk`
(the payment falls after the statement's due date) and `overdraft_breach` (the forecast's own
breach on the pay-from account by the payment date: past its limit, or below £0 with none). None while a commitment is tied to the card (the forecast may pay that bill instead, the same rule that hides `next_payment`).

**Legacy settings** (stored before T-10-4a validated them): an unknown role
reads as the account type's default, so a card stays credit; an unknown
strategy pays the full balance; an unknown cadence pays at each month-end
(under `statement_balance`, the card due date). The summary's accounts carry
`instalment_card` and `repayment_fix_needed` (a standard card still on
`scheduled`; nothing is changed for the user). A credit account also carries
`statement` (T-10-14a): `statement_balance`, `due_date`, `paid`, `missing`
(due date passed, no newer statement) from `statements.current_positions`, the
position the statements route uses; null when none is entered, absent on
other roles (`CashflowAccount` drops the key).

**UI**: `AccountSettingsModal` (opened from Wealth; its Statement block is `components/card/StatementBlock.tsx` + `StatementView.tsx`, with `StatementForm.tsx` for add/edit and `lib/statements.ts` for the rules and copy: the edit form sends every field, delete and "use this statement" each confirm first, naming the figure that changes; `lib/accountSettings.ts`
sends repayment fields only for a credit card and lists the repayment options: statement balance
(default when nothing is stored), full balance, fixed, instalments, scheduled only for an instalment
card or a card already on it, a stored percent-of-balance; pay day card due date (default) or a day
of the month, end of month and weekly only when already stored; the fix-this notice from
`repayment_fix_needed`; the API's `warnings` render under the control each is about via
`components/card/RepaymentWarnings.tsx` and `lib/repaymentWarnings.ts`, in live regions; the optional
Card APR input shows for fixed, percent and instalments; a save that returns warnings stays open with
"Saved. Read the notes below." and Done), `lib/credit.ts`; account
filter on Spending.

**Repayment not set up** (owner D8, T-10-12): `repayment_events` skips a card with no settings, or
with no pay day and a strategy other than `statement_balance`/`scheduled`. The UI derives the same
rule from the summary (`lib/credit.ts` `repaymentNotSetUp`, no API change) for a card that owes money,
and says "Repayment not set up, so this card isn't in your forecast": in the card's settings (and the
empty statement state then makes no payment claim), under the card's row on Cashflow, and as a row
on Home (`components/card/RepaymentNotSetUp.tsx`). Those links go to `/networth?settings=<id>`, which
opens the settings of an account the summary already holds and then drops the parameter. No fallback
payment is projected (`docs/known-gaps.md`).

**MCP**: `accounts`.

**Tests**: `api/tests/integration/test_accounts_credit_owed.py`,
`test_account_ownership.py`; `api/tests/unit/test_credit_sign.py`,
`test_card_link.py`, `test_card_installments.py`,
`test_card_repayment_once.py`, `test_card_payment_indicators.py`,
`test_card_statement_position.py`, `test_statement_balance_strategy.py`;
`api/tests/integration/test_card_statements_api.py`, `test_statement_strategy_api.py`.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `accounts`, `account_settings`, `repayment_schedule_items`, `card_statements`. Migration `f0a2b4c6d8e0` (T-10-4b) cleared repayment fields on `spending`/`savings` rows, with the old values in the plaintext backup table `account_repayment_backup_t10_4b` (drop in a later sprint; the downgrade restores from it). |
| 2 Purge | Yes, all four. |
| 3 Deletion | Cascade via `bank_connections` → `accounts`; `card_statements` also cascades from `users` (tested with SQLite foreign keys on). |
| 4 Demo mode | `/banking/accounts` served (no balances). The sample card has a repayment set up, so the "Repayment not set up" notice never shows in demo mode; the rule reads only the summary, which demo mode serves. **Gap**: repayments are in `KNOWN_DEMO_GAPS`. Statements served: the sample card (`sa4`) has one statement that reconciles with the sample summary (`sampleAccount.test.ts`). |
| 5 Ownership | Yes, every route here (`owned_account`, `require_owned_account_ids`). |
| 6 Scopes | Accounts list `finance:read`; settings, repayments and statements web only. |
| 7 Claude tools | `accounts` (read only). |
| 8 Audit | Not audited (web-only writes). |
| 9 Bank sync | Sync updates names, type, balances; settings and manual statements untouched. On a credit card, sync upserts the provider statement from the card balance response it already fetches (`services/provider_statements.py`); a bad or missing value stores nothing and never deletes a stored one. The GET reports `conflict` when manual and provider differ for the current period. Amount still due and unbilled are computed on read from the card's balance and transactions. |
| 10 Home | Cash and credit owed on the Cashflow and Wealth cards. Owned by Wealth. A card with no repayment set up gets its own "Repayment not set up" row linking to its settings. |
| 11 UI routes | Modal on `/networth`; `/networth?settings=<account id>` opens it. |
| 12 Tests | listed above. |
| 13 Docs | `CLAUDE.md` gotcha "Credit-card sign". |
