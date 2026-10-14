# App shell, navigation and Home

Four tabs (Home, Cashflow, Spending, Wealth): a top nav at `lg+` and a
bottom tab bar below `lg`. Home only summarises; every figure on it is owned
by the tab its card links to. Rules, Claude's changes, privacy, demo mode,
password and account deletion live in the user menu.

## Routes (`ui/src/App.tsx`, all inside `Layout`)

| Path | Page | Signed in |
|---|---|---|
| `/` | `HomePage` (marketing landing, `AiAssistantSection`) | no |
| `/login` | `LoginPage` | no |
| `/register` | `RegisterPage` | no |
| `/forgot-password` | `ForgotPasswordPage` | no |
| `/reset-password` | `ResetPasswordPage` | no |
| `/privacy` | `PrivacyPage` (`BetaInfoPage.tsx`) | no |
| `/terms` | `TermsPage` (`BetaInfoPage.tsx`) | no |
| `/home` | `OverviewPage` (Home tab) | yes |
| `/dashboard` | `DashboardPage` (Cashflow tab) | yes |
| `/insights` | `SpendingPage` (Spending tab) | yes |
| `/networth` | `NetWorthPage` (Wealth tab) | yes |
| `/commitments` | `CommitmentsPage` (off Cashflow) | yes |
| `/rules` | `RulesPage` (user menu) | yes |
| `/changes` | `ChangesPage` (user menu) | yes |
| `/r/:code` | `ImportSharedPage` | yes |
| `/oauth/authorize` | `OAuthConsentPage` | yes |
| `/callback` | `CallbackPage` | yes |
| `/transactions` | redirect to `/insights` | n/a |

There is no catch-all 404 route.

## Home (`OverviewPage`)

Loads every summary in parallel (`Promise.allSettled`) and shows:

- **Cashflow card** → `/dashboard`: cash, safe to spend, payday, 30-day
  sparkline, next 3 upcoming items.
- **Spending card** → `/insights`: money out this month vs last, 6-month
  sparkline, top 3 categories, budgets "X of Y on pace".
- **Wealth card** → `/networth`: net worth and changes, 12-month sparkline,
  and "Total owed" (cards plus loans, the API's `total_owed`, hidden at £0;
  `lib/homeOwed.ts`). Coming up labels a card repayment "{card} bill" and a
  loan's linked bill "{lender} loan payment" (T-10-14d).
- "N recurring payments detected" banner → `/commitments`; first-run
  "Connect bank" panel.

A new feature that Home summarises must keep the figure owned by its tab and
must work in demo mode, because Home is the first page a demo shows.

## Shared pieces

`components/Layout.tsx` (nav, user menu, sync strip, demo chip),
`ProtectedRoute`, `AnnouncementBanner` (dismissible notice, per-version
`localStorage` key), `components/ui/*` (Toast, ConfirmDialog, Sheet,
InfoTip, Sparkline, AnimatedNumber), `copy/statExplainers.ts`,
design classes in `ui/src/index.css` (see `CLAUDE.md`).
`ui/scripts/visual-check.mjs` screenshots pages at four viewports.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | none. |
| 2 Purge | n/a. |
| 3 Deletion | n/a. |
| 4 Demo mode | Every Home read is served. |
| 5 Ownership | n/a. |
| 6 Scopes | n/a. |
| 7 Claude tools | none. |
| 8 Audit | n/a. |
| 9 Bank sync | Sync strip in the header. |
| 10 Home | This feature. |
| 11 UI routes | All the above; a new page also goes in the nav or user menu and in `visual-check.mjs`. |
| 12 Tests | `BetaInfoPage.test.tsx`, `returnPath.test.ts`, `ui/devServer.test.ts`. |
| 13 Docs | `CLAUDE.md` "Navigation", `REDESIGN_PLAN.md`. |
