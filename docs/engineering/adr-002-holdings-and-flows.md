# ADR-002: Holdings and flows

**Status:** proposed (Sprint 11, T-11-1). Reviewers: eng-b, sec.
**Date:** 2026-10-15

## Context

Every money type in nilu. is wired by hand: assets, liabilities, card
statements, commitments, planned items and budgets each reach net worth,
the projection, Cashflow, Claude and demo mode through their own code.
Budgets (Sprint 09) and loans (Sprint 10) each missed surfaces that way.
Sprint 11 adds investments with a monthly contribution that must appear
everywhere, and a house and mortgage must later be a small change.

## Decision

Two concepts:

- A **holding** is something with a value on the balance sheet: an ISA, a
  pension, a house, a loan. It has a kind, a value history and a model that
  projects it forward.
- A **flow** is money moving on a date: a commitment, a planned item, a card
  repayment. Cashflow and safe-to-spend read flows only.

A holding meets a flow through one **link**: a commitment carries a
holding's contribution (money in) or repayment (money out of cash, debt
down). The holding is the source of truth for that commitment.

Holdings are a **code-level adapter over the existing `assets` and
`liabilities` tables**. No table is renamed, dropped or copied.

### 1. Mapping of current types

| Today | Becomes | Model | Link |
|---|---|---|---|
| Bank current and savings accounts | Not holdings. Cash, from synced balances | flat | none |
| Credit card accounts (+ `card_statements`) | Not holdings. Debt from synced balance; the statement drives `repayment_events()` | flat | card link (`card_account_id`), unchanged |
| `assets` isa, investment, pension, crypto | holding, group **investments** (owner D1) | growth | contribution |
| `assets` savings | holding, group savings | growth | none this sprint (one registry flag later) |
| `assets` property | holding, group property | growth | none |
| `assets` other | holding, group other | growth | none |
| `assets` mortgage, loan, other_liability | holding, group debt (legacy: negative valuation, 0% default) | growth | none; loan and other_liability can be replaced by a `liabilities` row (T-10-7b) |
| `liabilities` loan, finance, bnpl | holding, group debt | amortisation | repayment (existing `linked_commitment_id`) |
| `asset_valuations` | the holding's value history; "value today" = add a valuation | – | – |
| `asset_flows` | recorded past movements (decomposition only) | – | – |
| `commitment_rules` | flows (recurring). A linked one belongs to its holding | – | – |
| `repayment_events()` | flows (derived card repayments) | – | – |
| `planned_items` | flows (one-off and instalments) | – | – |
| `budgets` | a spending estimate (the projection's spending leg), not a flow or holding | – | – |

The "three sources of future money-out" lesson still holds: a contribution
is a commitment, so it is in source 1 and needs nothing new in Cashflow.

### 2. Kind registry

`api/app/services/holdings/registry.py` holds one frozen `HoldingKind` per
stored type:

```python
@dataclass(frozen=True)
class HoldingKind:
    key: str                     # "isa", "loan", ...
    source: Literal["assets", "liabilities"]
    group: Literal["investments", "savings", "property", "other", "debt"]
    model: Literal["growth", "amortisation", "flat"]
    is_debt: bool
    is_investment: bool          # the "Include investments" set (D1)
    link_role: Literal["contribution", "repayment"] | None
    surfaces: Mapping[Surface, str]   # every Surface -> "where" or "no: why"
```

`Surface` is a fixed enum: `NET_WORTH`, `PROJECTION`, `COMMITMENTS`,
`CASHFLOW`, `CLAUDE`, `DEMO`, `PURGE`, `DOCS`.
`INVESTMENT_KINDS = {k for k in KINDS if k.is_investment}` =
{isa, investment, pension, crypto}. The tick box, the history filter and
`investments_total` all read this one set. No debt kind can be in it
(validator rule).

**CI check** (`api/tests/unit/test_holding_registry.py`, runs in the
`required` job):

- `validate(KINDS)` passes: every kind declares every `Surface` with
  non-empty text; `is_investment` implies not `is_debt`; `link_role` is set
  only where the model supports it; the `DOCS` value names a file under
  `docs/features/` that exists.
- Self-test: a fake kind missing `CLAUDE` makes `validate` raise, and so
  does a fake debt kind marked as an investment.
- Coverage: every value in `ASSET_TYPES` and `LiabilityKind` has a registry
  entry, so a new stored type cannot skip the registry.

**Fail closed:** a stored type with no registry entry maps to kind
`unknown` (group other, model flat). It counts in net worth at its stored
value with its stored sign, is never filtered by any tick box, and logs a
warning with the plaintext stored type only (never the name or an id).
A test stores an unknown `asset_type` and checks net worth.

### 3. One generic link, one guard

New table **`commitment_links`** (one migration, in T-11-3):

| Column | Type |
|---|---|
| `id` | uuid PK |
| `user_id` | FK `users`, `ON DELETE CASCADE`, indexed |
| `commitment_id` | FK `commitment_rules`, `ON DELETE CASCADE`, **UNIQUE** |
| `asset_id` | FK `assets`, `ON DELETE CASCADE`, nullable, UNIQUE |
| `liability_id` | FK `liabilities`, `ON DELETE CASCADE`, nullable, UNIQUE |
| `role` | `contribution` or `repayment` (plaintext) |
| `commitment_created` | bool (opt-out deletes only a bill the link created) |
| `created_on` | date the link started (contributions count from here) |

CHECK: exactly one of `asset_id`, `liability_id` is set.

**Server-set fields:** `user_id`, `role`, `commitment_created` and
`created_on` (today, UK date) are set only by the server. Link requests use
`extra="forbid"` with an allowlist (`commitment_choice`: `new` or a
candidate id, and the contribution amount and day); a test sends each
server field and gets 422. The service checks the holding and the
commitment both belong to the caller (rule 6); a test uses another user's
real ids. No encrypted
column, so it is not in `KNOWN_ENCRYPTED_TABLES`; it joins `_OWNED_BY_USER`
before `Liability`, `Asset` and `CommitmentRule`.

**Uniqueness across kinds (sec item 2)** is the database's job:
`UNIQUE(commitment_id)` holds for every kind because **loans write a row
here too**. `liability_links.link` inserts the row in the same transaction
that sets `liabilities.linked_commitment_id`; `remove` deletes it; deleting
the liability or the commitment cascades it. The migration backfills a row
for every existing loan link (plaintext ids only, `INSERT … SELECT`). A
second link of the same commitment, of any kind, raises `IntegrityError`
whatever the race, and the route turns it into 409. For loans,
`liabilities.linked_commitment_id` stays the value Sprint 10 code reads this
sprint, so no loan behaviour or Sprint 10 test changes. Sprint 12 moves loan
reads to `commitment_links`, and a later release contracts the column.

**One guard (sec item 1):** `linked_commitments(db, user_id) -> dict[id,
LinkOwner]` in `services/linked_commitments.py` returns the union of
`commitment_links` rows and `liabilities.linked_commitment_id`.
`linked_commitment_ids()` keeps its name and returns its keys, so all eight
call sites get holding links with no change at the call site:
`card_links.link_card_commitments`, `repayments._card_ties`,
`commitments.sync_suggestions` and `commitment_from_transaction`, the
analytics router (list flag, web `PATCH`, skip, mark recurring),
`commitment_writes` (Claude update, dismiss) and `planning_writes` (undo).
`refuse_linked_edit` picks the 409 detail from the owner: loans keep
`linked_to_liability` and its message; holdings get `linked_to_holding`
("This payment follows your investment. Change it on Wealth, under
Investments."). The commitments list adds `linked_holding: bool` and
`holding_name` beside `linked_liability`. T-11-3 adds one test per call
site for a contribution link (the checklist's section 9 item), using
`test_linked_commitment_guards.py` as the template.

**Linking rules for a contribution** (Sprint 10 rules 1–6, with owner D2):

1. Opt in with "new": the server creates a confirmed monthly expense
   commitment labelled "{holding} contribution" and links it.
2. Opt in with an existing commitment: the client sends `commitment_id`
   chosen by the user. The server re-computes candidates (caller's own,
   expense, not dismissed, `card_account_id` null, not in
   `linked_commitment_ids()`) and accepts only one of them. **No auto-link,
   even with one match (D2).** The response returns the commitment taken
   over.
3. Opt out deletes the commitment only if `commitment_created`; otherwise it
   is unlinked and kept.
4. Editing the holding's contribution updates the commitment.
5. Deleting the holding keeps the commitment as an ordinary bill (D4).
   The link row cascades in the same request, so the guard lifts at once;
   a test then edits and dismisses the bill.
6. Another user's holding or commitment id is 404, nothing written.

Linking clears the holding's legacy `monthly_contribution` in the same
transaction (the UI prefills the commitment with it), so the two are never
both counted, and a later deleted commitment never brings it back.

### 4. Counted once (sec item 3)

| Where | Rule | Test |
|---|---|---|
| Safe-to-spend, summary, forecast | The contribution is a confirmed expense commitment, so `scheduled_outflows()` counts it once on its day. It is never in `_card_ties`, and `link_card_commitments` never ties it, even if its label names a card | one per path |
| Average spending | Payments matched to the commitment are excluded as today. An unmatched direct debit counts in the average too: a double count on the safe side (lower) | yes |
| Budget line | Budgets exclude commitment-covered categories as today; an unmatched payment stays in spend (safe side) | yes |
| Projection | The surplus leg keeps the commitment as a bill (−C); the holding engine adds C to the holding. Net worth is neutral that month. The legacy `monthly_contribution` is used only when there is no link | equality test |
| Net worth today and history | Value today = latest valuation + linked contributions (no growth) dated **strictly after** that valuation's date, on or after `created_on`, on or before today (UK), and at most 90 days after the valuation (the stale-nudge window, so at most about three are ever assumed), counted only while the commitment is confirmed. History uses the same rule at each point. So the bank drop on payment day is matched and net worth does not fall; a valuation dated on a payment day already includes it. A new valuation re-bases | valuation on a payment day; 6-month-old valuation adds at most 3 |
| Link removed (opt-out, commitment deleted) | The accrued contributions stop counting, so value today steps back to the last valuation. Opt-out writes a valuation at the current value today in the same request (user's key), so nothing steps; a web delete of the commitment can't, and the step down is accepted (safe side) | yes |
| Commitment deleted | Link row cascades: holding shows "not linked", contribution 0, the forecast no longer shows it leaving cash. Nothing raises safe-to-spend without the user acting | yes |

### 5. Projection engine (eng-b, T-11-4)

`api/app/services/holdings/projection.py`, pure (no DB). The adapter
`holdings/inputs.holding_inputs` (eng-b, T-11-4; T-11-3 adds the link and
registry lookups) builds inputs in the request with the caller's DEK; no background
job, no SQL filter on encrypted columns.

```python
@dataclass(frozen=True)
class HoldingInput:
    id: UUID; name: str; kind: str
    model: Literal["growth", "amortisation", "flat"]
    valuations: tuple[tuple[date, Decimal], ...]          # sorted
    paid_contributions: tuple[tuple[date, Decimal], ...]  # linked, since created_on
    growth_pct: Decimal          # own % > global default; legacy debts 0
    monthly_contribution: Decimal  # link amount if linked, else legacy; never both
    schedule: list[ScheduleRow] | None   # amortisation: liabilities.remaining_schedule()
    is_debt: bool

def project_holding(h, today, months) -> HoldingSeries      # .history, .forecast
def project_holdings(hs, today, months, *, include_investments=True) -> Projection
```

- Growth: v = v × (1 + r) + contribution each month, r = (1 + p)^(1/12) − 1
  (today's effective-annual rate, lead decision 2026-10-15), unrounded,
  penny-rounded at output. So no existing projection moves. Synthetic check:
  £0, £1,000 a month, 7%, 10 years = £171,051.73.
- Amortisation: value at a date = the schedule's balance then (as
  `owed_on`), so loans don't change. Flat: stored value held.
- `include_investments=False` drops only `INVESTMENT_KINDS`.
- Callers: `net_worth_projection` (replaces its per-asset loop and the
  liabilities loop; the cash waterfall is unchanged), a new
  `GET /api/v1/holdings/projection`, and `net_worth_history`
  (`include_investments`). An equality test ties the target projection to
  `project_holdings`.

### 6. Input bounds (sec item 5)

Rejected with 422 at the API: growth % from −100 to +50, value and
contribution up to 10,000,000, horizon up to 600 months,
`include_investments` a strict boolean. The engine uses the same range, no
hidden clamp (today's `_monthly_rate` clamps at −50; T-11-4 aligns it).
At most 100 holdings per user (409 past that), since every read projects
each (check-then-act, so not a hard bound the engine relies on). Worst
case, 100 holdings × 600 months at 50% with the largest values, stays
finite in `Decimal` and under 1 s through both `GET /holdings/projection`
and the net-worth projection; a test pins it.

### 7. Migration and rollback (sec item 4)

- One migration, `commitment_links` (T-11-3): create table, backfill loan
  rows. The backfill is idempotent and checked against the user:
  `INSERT … SELECT gen_random_uuid(), l.user_id, l.linked_commitment_id,
  l.id, 'repayment', l.commitment_created, <migration date> FROM liabilities
  l JOIN commitment_rules c ON c.id = l.linked_commitment_id AND c.user_id
  = l.user_id WHERE l.linked_commitment_id IS NOT NULL AND NOT EXISTS
  (SELECT 1 FROM commitment_links k WHERE k.commitment_id =
  l.linked_commitment_id)` (ids made in Python on SQLite). It logs the
  source and inserted counts only, through the `alembic` logger (prod drops
  app INFO, #187), never raises on a mismatch (migrations run at boot), and
  the counts are checked in the api container logs after deploy. Tests: a
  second run inserts nothing, a user mismatch is skipped, counts agree on a
  fixture with two loans, one linked. Additive; `assets` and `liabilities` untouched; no encrypted value
  read or copied; no migrate-on-read. T-11-4 needs none
  (`include_investments` is a parameter).
- Downgrade drops the table. It restores nothing, so no foreign key can
  break it. Holding links are lost on downgrade; their commitments stay as
  ordinary bills, so cash is still counted (safe side).
- Downgrade test, foreign keys on (SQLite `PRAGMA foreign_keys=ON`
  asserted, and Postgres up/down/up locally): upgrade, link a holding,
  delete the linked commitment and the holding, downgrade, upgrade.
- One Alembic head at merge: `down_revision` is re-pointed to main's head
  before merge and `test_card_link.py`'s single-head test passes. Revision
  ids are checked against open PRs first.

### 8. Adding a house and a mortgage (one ticket)

1. Property already exists as an asset kind (growth); nothing to build.
2. Add `MORTGAGE` to `LiabilityKind` (stored as `String(20)`, no
   migration) and its registry entry: group debt, amortisation, link role
   repayment, every surface declared. The CI check fails until it is.
3. Extend `replaces_asset_id` to accept a legacy `mortgage` asset.
4. Tests: amortisation schedule for a synthetic mortgage, link rules,
   net worth, projection, demo sample, Claude `list_holdings` key set.
5. UI: one chooser entry. Net worth, projection, Cashflow, commitments,
   Claude and purge already follow the registry and the link.

## Consequences

- New kinds are a registry entry plus tests; a missing surface fails CI.
- Until Sprint 12, loan links are stored twice (column and link row). Both
  are written in one transaction, and a test checks they agree after link,
  opt-out, delete, commitment delete, key-loss purge and account deletion
  (Postgres, foreign keys on), with every read 200 afterwards.
- Linked holdings' value today includes contributions the bank may not have
  paid, bounded to 90 days after the last valuation. It is shown with its
  "as of" date and the stale nudge as for loans.

## Ticket order

T-11-3 is split to stay under 400 lines: (a) registry and CI
check, no figure moves (unblocks T-11-4); (b) `commitment_links`
migration and the generalised guard; (c) the link API and counted-once
tests. T-11-4 builds on (a).
