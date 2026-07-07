# IA redesign: three-tab app (Cashflow / Spending / Wealth)

Status: **shipped through 2026-07-07.** IA phases 0–4 (#25–30), the
"Anonymize numbers" sample account (#31/#33), and the transparency-first
Spending rethink — quick wins + Home→**Cashflow** rename (#32), nothing-hidden
list (#34), **money-out default lens** (#35), full-ledger export + pace delta
(#36) — are all live. This document remains the source of truth for the
still-open work: the **Extension roadmap** below (targets, nudges, net worth
v2, holdings pricing, light theme) and the UX-addendum items tagged to future
phases. (The first tab is now **Cashflow**, not "Home".)

## Why

Two personas use nilu.:

- **Spenders** — want "where did my money go" and "am I okay until payday".
  Served well today.
- **Wealth-builders / high earners** — income exceeds expenses; they want
  "what am I worth, is my money working, am I on track". Served today by a
  single manual Net Worth tab. This is the persona the product is growing
  toward (see Extension section).

Today's nav has six destinations (Today, Activity, Spending, Plan, Wealth,
Rules), five of which serve the spender. The redesign collapses to three
questions → three tabs, with the same IA serving both personas:

| Tab | Question | Absorbs |
|---|---|---|
| **Home** | Am I okay right now? | Today + Plan (as "Coming up" strip + sub-page) |
| **Spending** | Where did it go? | Insights + Activity (transactions list inline) |
| **Wealth** | Am I getting richer? | Net Worth + accounts/connections management from Today |

Rules moves entirely into the user menu (it's already there on mobile).
Below-`lg` bottom tab bar goes from 5 cramped tabs to 3.

## Decisions already made (with the user)

1. **Backend scope**: fix the duplication properly. The transactions endpoint
   grows server-side filtering and an `excluded_reason` field derived from the
   backend's existing noise detection (`_detect_internal_transfers`, card-
   repayment matching). The client-side re-implementation in
   `TransactionsPage.tsx` (transfer pair-matching, Amex/Monzo-Flex string
   matching) is deleted. The list and the aggregates must never disagree.
2. **Scope is structural only.** The redesign reorganizes existing features.
   The Home nudge feed ships as a slot containing only the bank-coverage nudge
   (data we already have). Real nudges (cash drag, ISA allowance, tax) are an
   extension — see the last section.
3. **Sequencing**: four PRs, each independently shippable (main auto-deploys).
   Wealth first (additive), Spending merge last (most behavior-sensitive).
4. Old routes redirect (`/dashboard`→`/`Home, `/transactions`→`/spending`,
   `/commitments`→`/plan` sub-page, `/insights`→`/spending`). The `/r/:code`
   rule-import deep link is untouched.
5. Transaction row actions consolidate into a **detail sheet** (tap a row →
   category editor, "This repeats" cadence picker, "Always categorise like
   this" rule+backfill, "Pay on finance"). Bulk category select stays at the
   list level.
6. "Add" on Wealth is a **chooser**: "Connect a bank" (first, highlighted; copy
   says you can connect as many banks as you like) vs "Track something
   manually". Post-TrueLayer-callback success screen offers "Connect another
   bank". Button label becomes "Connect another bank" once ≥1 connection
   exists.

## Hard constraints (do not violate)

- **Per-user encryption** (`core/user_crypto.py`): transaction
  text/amounts and account details are encrypted columns. **No SQL
  filtering/aggregation on them.** Server-side transaction filtering means:
  load the user's rows (always scoped by user), decrypt via the request
  contextvar DEK, filter/sort/paginate in Python. This is how analytics
  already works.
- No background jobs can read bank data; nudge-style computation happens at
  request time.
- Every endpoint filters by `current_user`. JWT `typ` claims stay as-is.
- Repo stays generic/clonable — no personal infra in code or this doc.
- UI: use the design-system classes in `ui/src/index.css`; explicit base grid
  columns (`grid-cols-1 md:...`); `Number(...)` on money strings; nav
  breakpoint stays `lg`; GSAP respects `prefers-reduced-motion`.

## Feature inventory → new home (preservation checklist)

Nothing on this list may be lost. Tick items as their phase lands.

### Home (from Today/Dashboard + Plan/Commitments)
- [ ] Safe-to-spend hero + next payday date
- [ ] Stats: available cash / committed soon / savable (30d) / overdraft cushion
- [ ] Forecast chart — all horizons (payday/30/90/180/365), event tooltips,
      overdraft-limit line, lowest-point + breach warnings (`ForecastChart.tsx`)
- [ ] **New**: "Coming up" strip — next few commitments, credit repayments, and
      planned one-offs interleaved by date; links to the commitments sub-page
- [ ] Commitments sub-page (from `CommitmentsPage.tsx` + `PlannedItems.tsx`,
      merged): detected suggestions (confirm/dismiss/edit), confirmed regular
      income/expenses with monthly-equivalent totals, yearly section
      (£/yr ≈ £/mo, sorted by due), one-time items, add/edit modals incl.
      match-merchant field, planned items (one-off / recurring /
      installment plan with APR+fee calculator)
- [ ] Suggested-commitments review chip on Home ("N detected — review")
- [ ] First-run "Connect your first bank" empty state
- [ ] "Synced X ago" indicator; post-login sync banner (in Layout, unchanged)
- [ ] **New**: nudge-feed slot with the bank-coverage nudge only
- [ ] Credit "owed" card splits: balance → Wealth; next repayments → Coming up

### Spending (from Insights + Activity)
- [ ] Period selector: since payday / this month / last 30 / custom
- [ ] One persisted "exclude commitments" control (replaces Insights toggle +
      Activity checkbox — same feature twice today)
- [ ] Monthly spending bar chart, 6/12mo, cash-vs-credit split, worst month
      highlighted (`MonthlySpendingChart.tsx`)
- [ ] Headline tiles: total spent / paid from cash / charged to credit
- [ ] Category donut + bars with tx counts; top merchants ranked
- [ ] Click a tile/category/merchant → filters the transaction list **inline**
      (replaces the DrillModal from PR #20; numbers and list share one filter
      state and always reconcile)
- [ ] Transaction list: search, account / date-range / amount-range / merchant
      / type / multi-category filters, sort by date/amount, pagination
- [ ] "Show excluded" toggle surfacing noise (internal transfers, card
      repayments) with per-row `excluded_reason` labels — replaces the two
      "Hide internal transfers"/"Hide credit card payments" checkboxes
- [ ] Transaction detail sheet: category edit (+ add custom category),
      "This repeats" (weekly/monthly/every-few-months/yearly →
      `markTransactionRecurring`), "Always categorise like this"
      (`AddRuleModal` with backfill), "Pay on finance" (installment plan);
      shows account, raw description, Bill/Recurring/On-finance badges
- [ ] Bulk select + bulk category set (list-level, kept)
- [ ] CSV export of the filtered set
- [ ] Spent/Income/Net totals for the filtered set (fold into headline tiles)

### Wealth (from Net Worth + accounts management on Today)
- [ ] Net worth headline + change over period; history chart 6m/1y/2y/5y with
      bank/assets breakdown tooltip
- [ ] **New**: unified balance sheet — one grouped list (Cash / Savings /
      Investments & pensions / Property / Owed) containing bank accounts
      (live) and manual assets (with staleness chip, e.g. "3 mo old"), group
      subtotals, replaces the summary grid + separate asset cards
- [ ] Bank account rows: role chip (spending/savings/credit/excluded), balance,
      overdraft display; tap → account settings
- [ ] Account settings (from `AccountSettingsModal`): role, overdraft limit,
      credit repayment strategy (full_balance / fixed / installments /
      scheduled + `ScheduledRepaymentsEditor`), repayment cycle/day,
      pay-from account
- [ ] Manual asset rows: tap → update valuation (history list preserved),
      rename/delete; add via chooser
- [ ] **New**: add-chooser modal (connect bank vs track manually); "Connect
      another bank" labeling; ghost-row invitations in empty groups (optional)
- [ ] Connections management: connect / sync all / disconnect all / per-
      connection active-vs-needs-reconnection status
- [ ] Post-callback success screen: "X connected — connect another?"
      (`CallbackPage.tsx`)

### User menu (from nav + dashboard footer)
- [ ] Rules & categories page (all of `RulesPage.tsx`: personal + learned
      rules, packs, enable/disable, share/unshare links, import with preview,
      "apply all rules now" backfill) — linked from user menu at all sizes
- [ ] Change password (with re-key messaging), delete account (from dashboard
      footer → a small Settings section in the user menu)
- [ ] **New**: Demo mode toggle (see "Anytime PR — demo mode" below)

### Unchanged
Auth flows (register + recovery code, login, forgot/reset with by-design bank
purge), `/r/:code` import page, AnnouncementBanner, marketing HomePage,
security-reset banner, beta badge.

## Phases

Each phase: branch → PR → squash-merge (auto-deploys). Keep PRs reviewable by
a human: mechanical refactors ship separately from behavior changes, and a
phase may split into several PRs (aim well under ~800 changed lines of
non-mechanical diff each). After each phase run:
`docker compose --profile test build test && docker compose --profile test run --rm test`
(the test image copies source — rebuild or you run stale tests), and in `ui/`:
`npm run build`, `npm run lint`, `node scripts/visual-check.mjs` (dev stack up).

### Phase 0 — groundwork refactor (no behavior change) — **done 2026-07-06**

Landed notes: item 3's deep Decimal-coercion response mappers were deferred to
Phase 3 (they belong with the transactions-endpoint rework); shared types
landed in `ui/src/types.ts`. The analytics split kept
`analytics_service.py` as a compatibility shim over the new
`app/services/analytics/` package (with `common.py` and `planned.py` beyond
the modules listed below); new code should import package modules directly.

Purely mechanical PRs that make phases 1–4 small and human-reviewable. Every
PR here must produce zero visual/behavioral diff (visual-check screenshots
before/after should match).

**Frontend** (current pain: 9 files define their own `gbp`/`formatCurrency`;
`Transaction`/`Account`/`Commitment` interfaces re-declared per page; every
page carries inline modal components — Dashboard is 924 lines, Transactions
1,407):

1. `ui/src/lib/format.ts` — one `gbp()` (+ compact variant), `formatDate`
   family, and the shared `tnum` conventions. Delete the 9 local copies.
2. `ui/src/lib/cadence.ts` — `monthlyEquivalent`, `isYearly`, cadence labels
   (currently duplicated across CommitmentsPage/PlannedItems, and the
   yearly-as-every-12-months encoding is re-implemented in three modals).
3. Central Decimal-string coercion: response mappers in `services/api.ts`
   (typed per endpoint) so `Number(...)` sprinkles disappear from components.
   Types move to `ui/src/types.ts`, exported from the API layer — one
   declaration per entity. (Later option, not now: generate types from
   FastAPI's openapi.json.)
4. Shared toast system (`components/ui/Toast.tsx` + hook) with optional
   action button (needed by UX addendum B3); replace the ad-hoc toast in
   TransactionsPage and the bare `alert()`/`confirm()` calls (Transactions,
   NetWorth asset delete) with it / a small confirm dialog.
5. Extract inline modals into `ui/src/components/` as they stand (no
   redesign yet): ChangePasswordModal, DeleteAccountModal,
   AccountSettingsModal + ScheduledRepaymentsEditor, MakeRecurringModal,
   PayOnFinanceModal, Add/EditCommitmentModal, AssetModal/UpdateValueModal.
   Pages become thin (data + layout); components do the work — this is the
   standing convention going forward.

**Backend** (current pain: `analytics_service.py` is 1,242 lines mixing six
domains):

6. Split into a package `api/app/services/analytics/` — `cadence.py`,
   `commitments.py`, `repayments.py`, `forecast.py`, `spending.py`,
   `net_worth.py`, `summary.py` — with `__init__.py` re-exporting the public
   names so routers and tests don't churn. Pure file moves; run the full test
   suite (rebuild the test image) to prove it.
7. (Optional, later) split `routers/analytics.py` along the same seams —
   lower value, skip unless it blocks review.

### Phase 1 — Wealth balance sheet (additive move) — **done, PR #27**
The biggest visual change but lowest risk: no data-model changes.

1. Rebuild `NetWorthPage.tsx` as: headline + history chart (keep both), then
   the grouped balance sheet. Grouping: map account roles + `ASSET_TYPES` into
   the five groups above. Group subtotals; liability rows in `text-neg`.
2. Move from `DashboardPage.tsx` into the Wealth page: accounts grid +
   `AccountSettingsModal` + `ScheduledRepaymentsEditor` (extract the modals
   into `ui/src/components/` — Dashboard keeps nothing account-related), and
   the Connected-banks section (connect/sync/disconnect/status) as the balance
   sheet's management header.
3. Asset rows: staleness chip from `valuations[last].valued_at`
   (fresh <1mo · amber with age otherwise); tap opens the existing
   update-valuation modal.
4. Add-chooser modal; wire "Add asset" and "Connect bank" through it. Label
   logic: "Connect another bank" when `bankStatus.connections.length > 0`.
5. `CallbackPage.tsx`: success state gains "Connect another bank" (primary) +
   "Done" (ghost).
6. Move change-password / delete-account links from the dashboard footer into
   the user-menu dropdown (small; unblocks Phase 4).
7. Dashboard: net worth mini-stat in the credit card panel now links to the
   new page (unchanged behavior); remove the moved sections.

Acceptance: every Wealth checklist item above ticked except ghost rows
(optional); dashboard no longer shows accounts/banks; visual-check passes on
all viewports (watch the grid-overflow gotcha on the balance-sheet rows).

### Phase 2 — Home absorbs Plan — **done, PR #28**
1. Build the "Coming up" strip: merge next N=3–5 dated events from
   confirmed commitments (`/analytics/commitments`), credit
   `next_repayments` (already in summary), and planned one-offs — sorted by
   date. Link "All commitments →" to the sub-page.
2. Commitments sub-page at `/plan` (keep URL): `CommitmentsPage` merged with
   the `PlannedItems` card (one page for recurring + one-time + payment
   plans). Reached from Home, not the nav.
3. Suggested-commitments chip on Home when `status === 'suggested'` items
   exist.
4. Remove the standalone `PlannedItems` card and "Owed on credit" panel from
   Home (balance now lives in Wealth; repayments in Coming up). Remove
   `SpendingSnapshot` (redundant once Spending is one tap away; its
   cash/credit split lives in Spending's tiles).
5. Rename tab "Today" → "Home". Nav drops Plan: 5 desktop links, 4 mobile
   tabs (Home, Activity, Spending, Wealth).
6. Nudge-feed slot component on Home; only content: bank-coverage nudge
   ("safe-to-spend only sees {bank}...") shown when exactly 1 provider is
   connected; dismissible via localStorage.

Acceptance: Home checklist ticked; Plan gone from nav but `/plan` works;
forecast card untouched.

### Phase 3 — Spending merge (backend + frontend) — **done, PR #29**
Backend first (own PR if it helps review):

1. `GET /banking/transactions` grows: `search`, `category` (multi),
   `merchant`, `date_from/date_to`, `min_amount/max_amount`, `type`,
   `include_excluded` (default false), `sort`. All filtering in **Python after
   decryption** (encrypted columns — see constraints), reusing
   `_detect_internal_transfers` + the card-repayment matcher from
   `analytics_service` so the list shares the aggregates' noise logic.
   Response items gain `excluded_reason: 'internal_transfer' | 'card_payment'
   | null`. Distinct category/merchant lists either from a small companion
   endpoint or computed the same way (needed for filter dropdowns without the
   10k fetch).
2. Tests: unit tests for the filter/exclusion parity (a transfer pair excluded
   from `get_spending` must carry `excluded_reason` here), pagination, and
   user-scoping.

Frontend:

3. New merged Spending page: Insights content (selector, one exclude-
   commitments control, monthly chart, tiles, donut/bars, merchants) with the
   transaction list below, server-driven. Tile/category/merchant clicks set
   the shared filter state; list and figures reconcile by construction.
4. Transaction detail sheet (replaces inline row buttons + DrillModal); keep
   bulk-select mode and CSV export (export the current server-filtered set).
5. Delete: client-side transfer/CC detection, the 10k pagination loop,
   `DrillModal`, `/analytics/spending/transactions` usage if fully subsumed
   (check nothing else calls it before removing the endpoint — otherwise
   leave the endpoint).
6. Remove Activity from nav; redirect `/transactions` → `/spending` (or keep
   `/insights` as canonical and redirect both — pick one, add redirects).

Acceptance: full Spending checklist; a category total clicked equals the sum
of the listed transactions with no exceptions; API tests green (rebuild the
test image!).

### Phase 4 — Nav finalization + cleanup (incl. landing page) — **done**
1. Rules link out of desktop nav (user menu already has it from Phase 1/
   mobile); user menu gains a small "Settings" grouping (Rules, change
   password, delete account, log out).
2. Mobile tab bar → 3 tabs; desktop nav → 3 links. Delete `MOBILE_TABS`
   slicing hack.
3. Route redirects for all legacy paths; sweep for dead links/copy
   ("added to Plan" toast → "Added to your commitments — see Coming up").
4. Delete dead components (`SpendingSnapshot`, old pages), update CLAUDE.md's
   layout section and the statExplainers copy where surfaces moved.
5. **Landing page** (`HomePage.tsx`) — align with the new IA without changing
   overall positioning (see the decision note below):
   - Hero stays "safe to spend" (still the sharpest differentiator); the
     hero preview card gains a second stat row for net worth so the wealth
     story is visible above the fold.
   - Restructure the feature grid to mirror the three tabs: three primary
     question cards — "How much can I spend?" (Home: safe-to-spend +
     day-by-day forecast up to a year, folding in the current "What's
     coming?" card), "Where did it go?" (Spending: categories, merchants,
     months, cash vs credit), "Am I getting richer?" (Wealth: the full
     balance sheet — banks live via open banking, plus ISAs, pensions,
     property, crypto) — with a supporting row for rules/rule-pack sharing
     and multi-bank connection ("as many banks as you like" echoes the
     add-chooser copy).
   - Security section: content already matches the per-user encryption
     model — keep. Add one card for **demo mode** once it ships ("Show the
     app, not your numbers — one tap swaps every figure and name for
     realistic fakes"). Do not claim regulatory status for nilu. itself;
     TrueLayer's FCA authorisation may be cited (existing card does this
     correctly).
   - CTA "Go to dashboard" → Home route; footer tagline gains the wealth
     clause (e.g. "…what's coming, and what you're worth").
   - Keep GSAP treatment + `prefers-reduced-motion` guard.

   *Positioning decision*: hero remains spender-led for now because the
   wealth features are still manual-first. Revisit hero + landing positioning
   (wealth-first or dual-persona) when the Extension features (nudges,
   holdings-level pricing) land — noted again in the Extension section.
6. Full visual-check pass (every page × 4 viewports), scrollWidth vs
   clientWidth spot-checks, lighthouse-style tap-target sanity on the 3-tab
   bar.

## Anytime PR — Anonymize numbers — **SHIPPED (#31, then reworked #33)**

A user-menu toggle ("Anonymize numbers") for screenshots and showing the app
without exposing real figures. Header "Anonymized" chip is its own off-switch;
writes blocked while active; `sessionStorage` only.

Two iterations — the second is the current design:
1. **First cut (#31):** an axios response scrambler — money × a session
   constant `k`, deterministic name pseudonyms. Rejected by the founder: to
   keep totals reconciling the transform must be linear, which mathematically
   preserves *proportions*, so the real spending *shape* leaked through.
2. **Current (#33):** a fixed **sample account** (`ui/src/lib/sampleAccount.ts`)
   — a hand-authored fake ledger (fake banks/merchants/amounts) from which
   every endpoint (summary, spending incl. both lenses, transactions,
   net-worth, forecast, commitments, assets) is derived, so it reconciles by
   construction and stays browsable (filters apply to the fixed ledger). While
   active, an axios per-request adapter (`api.ts`) serves the sample instead of
   contacting the real API. Completely unrelated to the user; dates roll
   relative to today. Reconciliation guarded by `sampleAccount.test.ts`.
   `lib/anonymize.ts` is just the on/off store.

Known limitation: it's a *fixed* sample (same every session), not generated.

## UX review addendum (2026-07-05)

Findings from the design review of the mockups + existing system. Where these
conflict with `docs/mockups.html`, **this addendum wins**. Tags show which
phase implements each item.

### A — Color and visual language

- **A1 (Phase 1)** Rose (`neg`) means *needs attention*, not *is negative*.
  A mortgage shown in red every day is alarm fatigue. Balance sheet:
  structural liabilities (mortgage, installment balances on plan) render in
  neutral slate with a minus sign; rose is reserved for problem states
  (overdraft breach, expired connection, over-pace spending). Credit-card
  balances keep the amber/`warn` association they already have.
- **A2 (Phase 1)** Don't overload amber: it already means "credit". Staleness
  chips on manual assets are neutral slate with a clock icon; they escalate
  to amber only past ~6 months. (Amends the mockup, which used amber for all
  staleness.)
- **A3 (all phases)** Mint accent = interactive/brand only. Informational
  chips ("live") use muted styling so they don't read as buttons; anything
  mint-colored should be tappable.
- **A4 (Phase 4)** Contrast audit: `text-slate-500/600` on ink backgrounds at
  11–13px is borderline for WCAG AA (4.5:1). Audit explainer text, chip text,
  and axis labels; bump to slate-400 where it fails.

### B — Interaction patterns

- **B1 (Phases 1+3)** One universal pattern: **tap a row → detail sheet**
  (transactions, bank-account rows, asset rows). Bottom sheet below `lg`,
  centered modal at `lg+`. Rows are real `<button>`s with `focus-visible`
  rings and full-row hit areas — not small text links inside a row.
- **B2 (Phase 3)** Filter state must be legible: an active-filter chip row
  (each chip with ×, plus "clear all") above the transaction list. Tapping a
  category/merchant/tile adds a chip and scrolls to the list (smooth scroll +
  brief highlight so the jump isn't disorienting on mobile).
- **B3 (Phase 0 toast system; used everywhere)** Toasts standardize:
  message + optional action. Mark-recurring → "Added to your commitments —
  **View**". Dismissing a suggested commitment → "**Undo**". No bare
  `alert()`.
- **B4 (demo-mode PR)** The header "Demo data" chip is itself the off
  switch (tap → confirm-less toggle off), not just an indicator.

### C — Flows

- **C1 (Phase 2)** New-user setup checklist on Home, replacing the single
  "connect your first bank" hero after the first connection: ① connect your
  bank(s) → ② confirm your income and bills (copy says *why*: "your
  safe-to-spend becomes trustworthy once these are confirmed") → ③ add what
  your bank can't see (ISA, pension…). Steps check off from real state;
  dismissible; never returns once completed.
- **C2 (Phase 1)** Connection failure path: a TrueLayer error/cancel on
  callback must land back on Wealth with a retryable error banner — never a
  dead-end page.
- **C3 (Phases 1–2)** Empty states are designed, not default: each empty
  balance-sheet group gets a ghost-row invitation; empty "Coming up" links to
  add a commitment; the nudge slot renders nothing at all when empty (no
  "no nudges yet" card).

### D — Copy and tooltips

- **D1 (Phase 3, sweep in 4)** Terminology: today the same concept surfaces
  as "Plan", "commitments", "Bill" chip (`is_commitment`), and "Recurring"
  chip (`is_recurring`). Pick **"commitments"** as the single user-facing
  noun; transaction rows show **one** chip (Commitment), with recurring-but-
  unconfirmed shown only inside the detail sheet. Rename the `Bill` chip.
- **D2 (each phase)** New `EXPLAIN` entries (the InfoTip/statExplainers
  system is good — keep using it) for: staleness chips ("this value is as of
  the last time you updated it — tap to refresh it"), excluded transactions
  ("transfers between your own accounts and card repayments aren't spending,
  so we hide them from totals; show them with the toggle"), Coming up,
  savable, demo mode. Tooltip copy states the *consequence*, not just the
  definition.
- **D3 (Phase 4)** InfoTip on touch: ≥44px hit area, opens on tap, closes on
  outside-tap (today's icon is ~14px).

### E — Accessibility

- **E1 (Phases 1+3)** Sheets/modals: focus trap, Escape to close,
  `aria-modal`, focus returns to the invoking row. Row-buttons keyboard
  reachable in DOM order.
- **E2 (Phase 4 verify)** `prefers-reduced-motion` is respected by GSAP on
  the landing page — verify AnimatedNumber and the reveal hooks honor it too.
- **E3 (all phases)** State never by color alone: chips keep text labels,
  forecast breaches keep the ⚠ + text (both already true — keep it that way).

## Theming: dark stays; make light possible

The product's dark ink+mint theme **is the brand and stays the default** —
the neutral styling in `docs/mockups.html` is a mockup convention, not a
direction. Decision: dark mode is always available (it's the default); a
light theme becomes *cheap to add* rather than being built now.

How, without a big-bang restyle: pages currently hardcode palette classes
(~250 uses of `text-slate-*` / `bg-white/[…]` / `border-white/[…]` across
pages). As phases 1–3 rebuild each surface anyway, migrate to **semantic
tokens**: CSS variables (`--bg`, `--surface`, `--surface-2`, `--text-1/2/3`,
`--line`, plus the existing `accent/pos/neg/warn`) declared in `index.css`
and consumed via Tailwind config colors. Rules:

- New/rebuilt surfaces use only semantic tokens (enforce in review).
- The existing `.card`/`.btn-*`/`.chip-*` classes in `index.css` convert to
  tokens in Phase 0 or 1 (single file, low risk).
- A light theme is then one `[data-theme="light"]` variable block + a toggle
  in the user menu (system default via `prefers-color-scheme`, dark as
  fallback). Ship the toggle in Phase 4 **if** the light palette has had a
  real design pass (charts, orbs, and shadows all need light variants);
  otherwise it's the first Extension item. Never ship a half-designed light
  mode — dark-only is better than dark-plus-broken-light.

## Extension roadmap — the wealth-builder phase (planned, 2026-07-07)

The IA redesign, the anonymiser, and the transparency-first Spending rethink
are shipped. This phase serves the **wealth-builder persona** (income exceeds
spend; the daily question is "am I growing, is my money working, am I on
track"). The app has to feel *alive* for them — a net-worth number that moves
on its own is a reason to open it; one that flatlines until you type is a
chore. Two constraints bind every item here and are non-negotiable:

- **Encryption**: bank/asset data is per-user-DEK encrypted and the key is only
  held during a session. So all guidance/aggregation is **request-time Python
  after decrypt** (mirroring `get_summary`/`net_worth`); **no background job can
  read or compute over encrypted data** (it has no DEK — `require_dek()` raises
  `DEKUnavailableError`). Anything a scheduler touches must be *plaintext*
  (public market prices, statutory constants), never a user's figures.
- **FCA line**: nilu. is not authorised to advise. Every user-facing number is
  **factual arithmetic on the user's own data + a cited published fact**, never
  a personal recommendation. Copy pattern: "X is true; here's what that means
  in £", with source + as-of date (reuse the calculation-tooltip pattern from
  #24). A drift toward "move your money to Y" is a ship-blocker.

### Recommended sequence (value ÷ effort, with dependencies)

1. **Targets & projections** (M) — cheapest big win, no migration.
2. **Nudge engine v1** (M) — cash-drag + FSCS only (need just balances +
   constants); the Cashflow nudge slot already exists.
3. **Net worth v2** (L) — allocation + contribution-vs-growth; needs the
   `AssetFlow` primitive, so it follows the cheaper wins.
4. **Holdings-level pricing** (L/XL) — the retention engine, but the biggest
   build (market-data pipeline + scheduler); do it once the cheaper value has
   landed.
5. **Light theme** (L) — independent; its foundation PR is invisible, so it can
   run in parallel whenever.

### Per-area detail

**1. Targets & projections** — FIRE-style "when do I hit £X" + a milestone line
on the Wealth net-worth chart, from current contributions + a stated growth
assumption. *Compute*: pure request-time arithmetic, no persisted model for v1.
*First slice (one PR)*: `net_worth_projection()` in a new
`api/app/services/analytics/projections.py` + `GET /analytics/net-worth-projection`
taking `target_amount`, `monthly_contribution`, `annual_growth_pct` (defaults
from `get_summary`'s `savable`); render as a dashed forward extension on the
existing history chart. *FCA*: a projection with visible assumptions, labelled
"an estimate, not advice".

**2. Nudge engine** — a small Cashflow feed of honest, dismissible observations.
*v1 nudges (balances + constants only)*: **cash-drag** (idle liquid balance ×
(best-easy-access benchmark − assumed 0% account rate) → "£X/yr left on the
table") and **FSCS exposure** (group SPENDING+SAVINGS balances by decrypted
`provider_name` in Python, flag any group > £85k). *Later, opt-in*: ISA/pension
allowance countdown to 5 April (needs user-logged contributions — Open Banking
can't see them), and 60%-marginal-band awareness (needs self-declared income, a
new encrypted field). *Compute*: `analytics/nudges.py:get_nudges(db,user)` +
`GET /analytics/nudges`, reusing `_load`/`resolve_roles`. *Key trick for "no
background job"*: published UK facts (FSCS £85k, ISA £20k, bands, the 5-April
boundary) and the one market-varying input (a curated best-easy-access rate with
`as_of` + source) live in a **code module** `api/app/services/reference/uk_reference.py`,
refreshed by a human editing the file and deploying — never a runtime fetch or a
DB row a job refreshes. *UI*: generalise the existing single nudge slot in
`DashboardPage.tsx` into a ranked feed (max 2–3, dismissible, calc tooltip with
source/as-of). *Risk*: rate staleness (always render "the best rate on {date}");
FSCS brand-vs-licence (£85k is per licence — ship a brand→licence map + caveat).

**3. Net worth v2** — allocation views (by asset class / tax wrapper / provider)
and a **contribution-vs-growth decomposition** ("you rose £8k — £5k was saving,
£3k markets"). *Data model*: the decomposition needs to know deposits vs growth,
which today's `Asset`/`AssetValuation` (value snapshots) can't tell apart — add
an **`AssetFlow`** table (asset_id, amount, flow_date; a recorded
deposit/withdrawal). Allocation needs `tax_wrapper`/`provider` columns on
`Asset` (slice 2). *Compute*: request-time Python; growth = Δvaluation −
Σflows in the window. *First slice*: migration adding `AssetFlow` only +
`POST /assets/{id}/flows` + an optional "I added/withdrew £__ since last update"
field on the existing update-value modal; then the decomposition on the Wealth
headline.

**4. Holdings-level assets** — ticker + units so market prices auto-update
valuations (the chart moves on its own). *The hard constraint*: a cron **cannot**
write `units × price` into an encrypted valuation (no DEK). *Split along the
encryption line*: **prices are public → plaintext** `instruments` +
`instrument_prices` tables a scheduler *can* refresh; **units are the user's →
encrypted** (`Asset.units: UserEncryptedDecimal`, nullable, + `instrument_id`,
`pricing_mode`). The live valuation = units (decrypted in-session) × latest
plaintext price, computed request-time. Staleness chips flip to "live" per
priced asset. *First slice (no scheduler yet)*: migration for the price tables +
`Asset.units`, an `/instruments/search` over seed data, and request-time pricing
against a single provider — add the background price-refresh job after. *Decision
needed*: which market-data provider (cost, ToS on caching prices).

**5. Light theme** — migrate the ~250 hardcoded `slate-*`/`bg-white/[…]` classes
to **semantic CSS-variable tokens** so a light theme is a variable block + a
user-menu toggle. *Compute*: purely client-side; theme class set on
`documentElement` via a tiny inline script in `index.html` (reads localStorage
before React mounts, no FOUC). *First slice (invisible)*: define the token block
in `index.css` — `--surface`, `--surface-2`, `--bg`, `--text{,-muted,-subtle}`,
`--border{,-strong}`, `--shadow-*` — with a dark default and a `.theme-light`
override; then migrate surfaces incrementally as they're touched. Ship the
user-menu toggle only once charts/orbs/shadows have light variants — never a
half-designed light mode (dark stays the default and the brand).

### Decisions needed from the founder before building

1. **Nudge rate sourcing** — curated-in-code best-easy-access benchmark (v1, a
   human updates it on deploy) vs a licensed rate feed later? Start curated.
2. **Market-data provider** for holdings — which API, at what cost, and does its
   ToS allow caching prices in our `instrument_prices` table?
3. **Self-declared income** — add an (encrypted) income field to unlock the
   60%-marginal-band nudge and better projections, or skip that nudge for now?
4. **Light-theme priority** — slot it into the sequence now, or defer until the
   wealth features land?

### Also parked (from earlier)

**Landing-page repositioning**: once the wealth features exist, revisit the
spender-led hero ("safe to spend") toward the wealth-builder pitch
(subscription-not-referrals; can't-read-your-data trust). Consider a public
read-only demo account for logged-out visitors — could reuse the
`sampleAccount.ts` fake dataset built for the anonymiser.

## Handoff notes

- Dev stack: `docker compose up -d` (api :8000, ui :5173). Migrations run at
  container boot only — `docker compose restart api` after pulling migrations.
- Mockups for all six target surfaces live in **`docs/mockups.html`** (open in
  a browser): Wealth balance sheet, Home, Spending, add-chooser, transaction
  detail sheet, landing page. They are structure/hierarchy references in a
  neutral light style — build against the existing ink+mint design system,
  not the mockups' styling. The UX review addendum below amends several
  details in them (liability color, staleness chip color, "live" chip
  styling); the addendum wins where they conflict.
- Workflow: branch → PR → squash-merge; pushing `main` auto-deploys. Standard
  Claude Code attribution lines on commits/PRs.
