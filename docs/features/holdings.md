# Holdings and their projection (ADR-002)

One model over the balance-sheet tables: a **holding** is anything with a
value (an ISA, a pension, a house, a loan), with a kind from the registry, a
value history and a model that projects it forward. Holdings are a code
adapter over `assets` and `liabilities` (see [net-worth.md](net-worth.md)
and [liabilities.md](liabilities.md)); no table of their own. Design:
`docs/engineering/adr-002-holdings-and-flows.md` (sprint 11).

## Code

**API**:

| Route | Auth |
|---|---|
| `GET /api/v1/holdings/projection` | `CurrentUser` (`months` 1–600, default 120; optional `holding_id`, 404 unless it is one of the caller's investments) |

Each investment (registry `is_investment`: isa, investment, pension,
crypto, owner D1) and their total: the valuations entered as history
(nothing guessed between them), then the engine's monthly forecast with
`paid_in` (value today plus the contributions from today), and the answer
sentence's figures to the nearest £1,000. A holding with no growth % of its
own uses `annual_growth_pct` (−100..50, default 5%), the same parameter and
default as the target projection, so the two agree.

**Services** (`api/app/services/holdings/`):

- `registry.py`: one `HoldingKind` per stored type (source, group, model,
  is_debt, is_investment, link role, every surface declared); unknown types
  fail closed (an unknown liability kind is still debt).
- `projection.py`: the engine, pure. Growth compounds at the holding's own
  yearly % (effective annual, r = (1 + p)^(1/12) − 1) plus the monthly
  contribution, unrounded, rounded once on output; amortisation takes the
  loan schedule (`liabilities.owed_on`); anything else is flat. Value today
  = latest valuation on/before the day plus linked contributions paid
  since (at most 90 days after it). Bounds: growth −100..50%, 600 months.
- `inputs.py`: `holding_inputs`, the one adapter (request-time decrypt,
  user-scoped), and `without_investments` for the "Include investments"
  choice.
- `graphs.py`: the investment graph payload.

**UI (T-11-5)**: the investment graph at `/networth/investments`
(`pages/InvestmentsGraphPage.tsx`, `components/wealth/InvestmentGraphView.tsx`, helpers in
`lib/investments.ts`): look-ahead 5/10/20/30 years and the holding choice (in the URL as
`?holding=`), the API's sentence and inputs line, Worth (entered values as dots, dashed
forecast) and Paid in, a hidden table for screen readers. A holding with no rate of its own
grows at the target form's `wealth.growth`.

**Who calls the engine**: the target projection
(`analytics/projections.net_worth_projection`, per-holding series and
liabilities), `net_worth.assets_total` (so the summary, position, history
and projection month 0 share one value today), and the graphs route. An
equality test ties the projection to the engine.

**Include investments**: `include_investments=true|false` (only those two
words; default true) on `GET /api/v1/analytics/net-worth-history` and
`GET /api/v1/analytics/net-worth-projection` drops the investment kinds and
nothing else. Safe-to-spend, the summary and the forecast don't take it.

**Input bounds** (422): growth % −100..50, asset value ±10,000,000, monthly
contribution 0..10,000,000, projection target ±100,000,000.

**Tests**: `api/tests/unit/test_holding_projection.py` (hand-checked
£0 / £1,000 a month / 7% / 10 years = £171,051.73, every month; bounds;
100 holdings × 600 months under 1 s), `test_holding_inputs.py` (adapter,
equality with the target projection, fail-closed kinds),
`api/tests/integration/test_holdings_projection_api.py` (route, 404 on a
foreign id, 422s, include_investments).

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | none (adapter over `assets` and `liabilities`). |
| 2 Purge | n/a: no table; the source tables are purged. |
| 3 Deletion | n/a: no table. |
| 4 Demo mode | gap until T-11-8: `/holdings/projection` is in `KNOWN_DEMO_GAPS`. |
| 5 Ownership | No account ids. `holding_id` is checked against the caller's own investments (404). |
| 6 Scopes | Web only. Claude's read-only `list_holdings` is T-11-7. |
| 7 Claude tools | none yet (T-11-7). |
| 8 Audit | Read-only. |
| 9 Bank sync | Computed on read. |
| 10 Home | Not yet (Home's investments total is T-11-6/7). |
| 11 UI routes | `/networth/investments` (`InvestmentsGraphPage`; in `visual-check.mjs`; linked from Wealth in the next PR). |
| 12 Tests | listed above. |
| 13 Docs | this file; net-worth.md points here. |
