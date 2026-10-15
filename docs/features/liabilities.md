# Liabilities (loans, retail finance, buy now pay later)

Debts the user enters by hand, since TrueLayer has no loan data: kind,
lender, balance "as of" a date, APR, payment, how often, start date and an
optional final payment date. "I repay this loan irregularly" (`opted_out`)
makes the payment optional. Stage 1 of the liabilities spec (T-10-7a).
Net worth subtracts liabilities on every surface (T-10-7b, see
[net-worth.md](net-worth.md)); the commitment link (T-10-8) and the Wealth
list (T-10-10) build on it.

## Rules

- **Derived on read, never stored**: next payment, payments left, payoff
  date, interest left and total cost (`services/liabilities.py`). Money stays
  `Decimal` throughout.
- **APR is the effective yearly rate** UK lenders quote. The rate per payment
  is (1 + APR)^(1/n) − 1 for n payments a year (monthly: 12; every 4 weeks:
  13; every 2 weeks: 26; weekly: 52). Interest is charged each period on the
  balance, rounded half-up to the penny, then the payment is taken.
- **The start date sets the payment day.** The schedule runs from today's
  balance: the next payment is the first on or after today, and after the
  as-of date (that day's payment is already in the entered balance), so it is
  never a past date. A stored row whose schedule no longer clears shows null
  schedule figures rather than failing the list.
- **Bounded**: a payment that doesn't cover the first period's interest, or
  doesn't clear the balance within 50 years (600 months), is a 422 with a
  plain message. Nothing is stored.
- **Mortgage (T-12-6, ADR-002 section 8):** `kind: "mortgage"` is a
  liability like a loan (Loans and finance, amortisation, linked repayment;
  registry entry `liabilities:mortgage`). Bounds (sec): balance up to
  £10,000,000 (other kinds stay at £1,000,000), APR at most 25%, and the
  schedule must clear within 40 years (422 otherwise). A bill it creates is
  labelled "{lender} mortgage payment" and follows lender renames. Its guard
  409 keeps the code `linked_to_liability` with the message "This payment
  follows your mortgage…", and the commitments list sets `linked_mortgage`.
  `replaces_asset_id` also takes a legacy `mortgage` asset. Claude sees it
  only in `liabilities_total`, never in `list_holdings`.
- **Linked repayment (T-10-8):** a liability with a payment carries its
  repayment as one commitment, linked by the stored `linked_commitment_id`
  (FK, `ON DELETE SET NULL`, unique; set only by the server). Rules: a new
  liability creates a confirmed commitment (label = lender), or links the one
  existing expense commitment with the same amount and cadence (more than
  one: 409 `choose_commitment` with the candidates; the client resends
  `commitment_choice` = a candidate id or `new`, and the server re-computes
  the candidates and accepts nothing else). Editing the payment or cadence
  updates it (and renames a bill the liability created when the lender is renamed). Opting out deletes the commitment only if the liability created it (`commitment_created`); a bill the user already had is only unlinked and kept with no end. Opting back in links again. A card repayment commitment (`card_account_id`) is never a candidate. The
  linked commitment can't be edited, skipped, dismissed or undone elsewhere
  (409, see [commitments.md](commitments.md)), and detection never suggests
  its payments again. Its
  `ends_on` is the final scheduled payment, so a paid-off loan stops leaving
  the forecast. Deleting the liability without opting out keeps the
  commitment as an ordinary bill with no end (owner D4). Cadences map to
  `monthly`, `weekly`, or `custom_days` 14/28. Linking also writes the
  loan's `commitment_links` row in the same transaction (ADR-002), so a bill
  can't be linked to a loan and a holding at once; opting out and deleting
  the liability remove it.
- **Today's balance:** linked to a *confirmed* commitment, it follows the schedule from the as-of
  balance (payments due before today count as made, since they are in the
  forecast), and `paid_off` is true once every payment is made. Not linked
  (repaid irregularly, or its commitment was deleted or isn't confirmed), it is the entered
  balance: assuming payments that may not have happened would understate the
  debt. An as-of date more than 90 days old sets `balance_stale` so the UI
  asks for an update.
- Opted out: no schedule, so the schedule figures are null.
- **Overpayment (T-10-11, read-only):** a lump sum paid today with the
  payment unchanged gives payments and interest before/after and saved, and
  both payoff dates. The settlement figure is today's balance plus up to 58
  days' interest at the effective APR (UK early settlement), and caps the
  lump sum. A plain note says savings could earn interest instead; nothing
  recommends a choice (no advice). No UI yet (needs a ux spec).
- List order: APR high to low, then balance high to low, then lender A to Z.
- At most 50 liabilities per user (409 past that), since every read
  amortises each row.

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/liabilities` | `CurrentUser` |
| `POST /api/v1/liabilities` | `CurrentUser` |
| `GET /api/v1/liabilities/{liability_id}` | `CurrentUser` |
| `PATCH /api/v1/liabilities/{liability_id}` | `CurrentUser` (merged terms re-checked) |
| `DELETE /api/v1/liabilities/{liability_id}` | `CurrentUser` |
| `GET /api/v1/liabilities/{liability_id}/overpayment` | `CurrentUser` (read-only; `lump_sum` > 0, at most the settlement figure) |

`POST` also takes `replaces_asset_id`: the caller's own `loan` or
`other_liability` asset (404 for a foreign or unknown id, 422 for any other
type), deleted in the same transaction that creates the liability (T-10-7b).
A second call with the same id gets 404 and creates nothing. `PATCH` refuses
the field.

Requests allow-list the user's terms (`extra="forbid"`): no id, user id,
link or derived figure is accepted. Money is a decimal string, 2 dp, more
than 0 and at most 1,000,000; APR 0 to 100; lender at most 100 characters;
as-of date not in the future; start date at most a year ahead; final payment
after the start date; kind and cadence are enums.

**Card instalment plans (T-12-5a, ADR-002 kind `card_plan`)**: a purchase
repaid in monthly instalments plus a fee inside a credit card (Amex Plan It,
Monzo Flex).

| Route | Auth |
|---|---|
| `GET /api/v1/card-plans` | `CurrentUser` |
| `POST /api/v1/card-plans` | `CurrentUser` (card ownership-checked, must be a credit card; at most 50 a card, 409) |
| `PATCH /api/v1/card-plans/{plan_id}` | `CurrentUser` (terms only; the card is fixed) |
| `DELETE /api/v1/card-plans/{plan_id}` | `CurrentUser` |

Terms allow-listed (`extra="forbid"`): name (1-100), balance up to
10,000,000, instalment, monthly fee £0-£1,000 a month, APR 0-100 (optional),
instalments remaining 1-120, next instalment within a year of today.
Instalment dates that have passed come off at read time
(`services/card_plans.figures`). Owner D4 (2026-10-15): while the plan has
its card it is never added to net worth, Total owed or Claude's totals on
its own: a provider in `card_plans.PLAN_IN_CARD_BALANCE` (code list only,
none yet) holds it in the card balance; any other is hidden until confirmed
(`provider_confirmed` false, and the UI says "Not in net worth yet"). A plan
whose card has gone (`card_account_id` SET NULL on disconnect) counts as
standalone debt in `liabilities_total` and the projection. The instalment
plus fee (`card_plans.monthly_total`) leaves the bank on the card's next pay
day on or after each instalment date, or on the instalment date when the
card has no pay day or has gone (`repayments.plan_instalment_events`, added
in `scheduled_outflows` after the per-card choice, so a commitment tied to
the card never drops it). It counts in the Cashflow forecast and
safe-to-spend whatever the provider's status, and is never a commitment.
Past instalments are on the card already (statement or unbilled) and are
not added again (T-12-5b). Claude's `forecast` gets these events labelled
"Card plan instalment", never the plan's name (sec S-7: plans reach Claude
only as totals); the app shows the name.
Home and Cashflow "Coming up" (`next_repayments`, from `repayment_events`)
don't list instalments yet; T-12-7b shows them. When the first provider is
verified (its card balance holds the plan), a `full_balance` repayment
already pays the plan's remaining balance, so that card's repayment must then
leave out the plan's principal, or the instalments count twice (today that
can only overstate, the safe side).

**Tables**: `card_plans` (encrypted `name`, `balance`, `instalment`, `fee`,
`apr`; plaintext `card_account_id`, `instalments_remaining`, `next_date`;
migration `e5f7a9b1c3d5`, downgrade drops it).
`liabilities` (encrypted `lender`, `balance`, `apr`, `payment`;
plaintext `kind`, `cadence`, dates, `opted_out`, `linked_commitment_id`);
`commitment_rules.ends_on` (migration `f0a2b4c6d8e1`).

**Services**: `services/liabilities.py` (`amortise`, `period_rate`,
`first_payment_after`, `remaining_schedule`, `derived_figures`,
`current_balance`, `owed_on`), `services/liability_links.py` (`candidates`,
`link`, `sync`, `remove`, `release`).

**Cashflow** (P2, T-10-14b): Cashflow also reads the list so a linked bill
reads "{lender} loan payment" in Coming up and the forecast (cashflow.md).

**UI** (T-10-10): `/networth` balance sheet, group "Loans and finance"
(`components/wealth/LiabilityRow.tsx`, `lib/liabilities.ts`): rows in the
API's order (APR high to low), each a button that opens the edit form; line 2
from the API's figures only; `Update balance` / `Paid off` chips; the group
subtotal = asset liability rows + the API's liabilities total (shown once);
its own load error with Try again (no subtotal then); the both-counted
notice with **Replace an entry** when a `loan`/`other_liability` asset and a
liability exist. The add/edit form (`components/wealth/LiabilityForm.tsx`,
`lib/liabilityForm.ts`) is a labelled dialog that checks only required,
number and date format (every other rule is the server's 422), sends every
term with money and APR as typed strings, shows the "Which bill is this?"
step on a 409 `choose_commitment` (the choice goes with one more request),
confirms delete, opt-out and asset replacement naming the figure that
changes, and toasts by `link_result`. The chooser's third item opens it
("Add a loan or finance"); mortgages and other debts stay balance-sheet items.
A commitment edit, skip or dismiss that gets 409 `linked_to_liability` shows
the API's message with a link to Wealth.

**Tests**: `api/tests/unit/test_amortisation.py` (hand-checked schedule for
the synthetic £9,000 / £200 a month / 11% loan),
`api/tests/integration/test_liabilities_api.py`,
`test_liability_commitment_link.py` (rules 1-6), `test_liability_overpayment.py`, `test_mortgage.py`, `test_reset_purge.py`,
`test_oauth.py` (Claude tokens refused).

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `liabilities`, migrations `d8e0f2a4b6c8` (new table) and `f0a2b4c6d8e1` (link, `commitment_rules.ends_on`); downgrades drop them. `card_plans` (`e5f7a9b1c3d5`; downgrade tested with foreign keys on after the card was deleted). |
| 2 Purge | Yes, before `commitment_rules` in `_OWNED_BY_USER` (the reset seed links them, so the order is tested). `card_plans` before `account_settings`, seeded in the reset test. |
| 3 Deletion | Cascade from `users`; `test_liabilities_api.py` deletes an account with foreign keys on. |
| 4 Demo mode | `GET /api/v1/liabilities` served by `sampleAccount.ts` (two synthetic liabilities that reconcile with summary, position and history). Card plans: no screen reads them until T-12-7b, which adds a sample plan in the same PR. |
| 5 Ownership | No account ids. Liabilities load by id and user; another user's id is a 404 like an unknown one. |
| 6 Scopes | Web only (`test_oauth.py` checks). |
| 7 Claude tools | none. Claude can't read liabilities in this stage. |
| 8 Audit | Web-only writes, not audited. |
| 9 Bank sync | Not touched; figures are computed on read. |
| 10 Home | Home's net worth (from position or summary) subtracts liabilities. |
| 11 UI routes | none new; rows live on `/networth`. |
| 12 Tests | listed above. |
| 13 Docs | this file. |
