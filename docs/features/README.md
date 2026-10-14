# Feature map

What nilu. does, where each feature lives, and everything it touches. Read
this before changing a feature; update it in the same PR as the change.

- One file per feature in this folder. Each lists its API routes, tables,
  services, UI, MCP tools and tests, then answers the **touchpoints
  checklist** below for that feature.
- [`../known-gaps.md`](../known-gaps.md) lists gaps found while writing these
  docs (things missing from a touchpoint, stale copy, untested paths). Fix one
  and delete its line.
- `CLAUDE.md` holds the conventions; these docs say where each feature meets
  them.

## Features

| Feature | Doc | Where users see it | Claude (MCP) | Demo mode |
|---|---|---|---|---|
| Sign-up, login, password, delete account | [auth-and-account.md](auth-and-account.md) | `/login`, `/register`, user menu | no | n/a |
| Per-user encryption, key-loss purge, account deletion | [data-lifecycle.md](data-lifecycle.md) | reset password, delete account | no | n/a |
| Bank connections (TrueLayer) | [bank-connections.md](bank-connections.md) | Wealth, Home first-run | no | by design not sampled |
| Bank sync and freshness | [bank-sync.md](bank-sync.md) | login, Wealth, Cashflow | `sync_status`, `refresh_banks` | gap: sync-status |
| Accounts, roles, card repayments | [accounts.md](accounts.md) | Wealth > account settings | `accounts` | gap: repayments |
| Transactions | [transactions.md](transactions.md) | Spending list, detail sheet | `recent_transactions`, `search_transactions` | served |
| Categorisation and rules | [rules.md](rules.md) | user menu > Rules, `/r/:code` | `rules`, `rule_impact`, `preview_rule`, `create_rule_pack` | gap: shared preview |
| Safe to spend and forecast | [cashflow.md](cashflow.md) | Cashflow tab, Home | `cashflow_summary`, `forecast` | served |
| Commitments (recurring bills and income) | [commitments.md](commitments.md) | Cashflow > Commitments | `commitments`, `update_commitment`, `dismiss_commitment` | served |
| Planned events (one-offs, instalment plans) | [planned-events.md](planned-events.md) | Commitments page, Spending | `list_planned_events`, `add_planned_event`, `remove_planned_event` | served |
| Nudges | [nudges.md](nudges.md) | Cashflow tab | no | served |
| Spending insight | [spending.md](spending.md) | Spending tab, Home | `spending`, `spending_trend` | served |
| Net worth and assets | [net-worth.md](net-worth.md) | Wealth tab, Home | no | served |
| Liabilities (loans, finance, BNPL) | [liabilities.md](liabilities.md) | Wealth tab (T-10-10) | no | no UI reads yet |
| Budgets | [budgets.md](budgets.md) | Spending > Budgets, Home, Cashflow forecast | `list_budgets`, `set_budgets`, `pause_budget`, `resume_budget`, `remove_budget` | **gap: not served** |
| Claude's changes (audit, undo, keep) | [claude-changes.md](claude-changes.md) | user menu > Changes made by Claude | every write tool | served (empty) |
| Claude connector (MCP server, OAuth) | [claude-connector.md](claude-connector.md) | `/oauth/authorize`, landing page | all tools | by design not sampled |
| Demo mode ("Anonymize numbers") | [demo-mode.md](demo-mode.md) | user menu | no | it is the feature |
| App shell, navigation, Home | [app-shell.md](app-shell.md) | every page | no | n/a |
| Platform: health, CI, deploy | [platform.md](platform.md) | none | no | n/a |

## The touchpoints checklist

Every feature doc has a `## Touchpoints` section answering each row below:
**yes** (and where), **no** (and why that is right), or **gap** (and a line in
`known-gaps.md`). When you add or change a feature, walk this list. Budgets
missed row 4, which is why budgets can't be demoed.

| # | Touchpoint | What to do | Enforced by |
|---|---|---|---|
| 1 | **Tables and migrations** | New table or column gets an additive Alembic migration with a working `downgrade()`. Money and free text use `UserEncrypted*` columns. | review; `CLAUDE.md` gotchas |
| 2 | **Key-loss purge** | Any table holding a user's encrypted data is deleted by `api/app/services/key_loss_purge.py`. | `api/tests/integration/test_reset_purge.py` (encrypted tables only) |
| 3 | **Account deletion** | Table has `ondelete="CASCADE"` to `users.id` (or to a parent that has it), in the model and the migration. `POST /api/v1/auth/delete-account` relies on it. | nothing yet (see known gaps) |
| 4 | **Demo mode** | Every GET the UI calls is served by `sampleResponse` in `ui/src/lib/sampleAccount.ts`, with sample data that reconciles with the rest of the sample account, or is listed in `UNSAMPLED_BY_DESIGN` / `KNOWN_DEMO_GAPS` with a reason. | `ui/src/lib/sampleCoverage.test.ts` |
| 5 | **Account ownership** | Any route taking an `*account_id` checks it with `core/ownership.py`. | `api/tests/integration/test_account_ownership.py` (write routes) |
| 6 | **Auth and scopes** | Routes are web-only (`CurrentUser`) unless Claude needs them; then `CurrentUserOrMcpRead`, `CurrentUserOrMcpRulesWrite`, `PlanningWriter` or `BudgetsWriter`. Never auth, bank-connection or account-management routes. | `api/tests/integration/test_oauth.py` (hand-listed) |
| 7 | **Claude tools** | New MCP tool in `api/mcp/server.py` with the right annotations, listed in `api/mcp/README.md` and the reviewed set. | `api/mcp/tests/test_tool_annotations.py` |
| 8 | **Claude's writes are audited** | A Claude write goes through `services/planning_writes.run_write` / `run_batch` with its fields in `TARGETS`, so it shows on the Changes page with undo. | `api/tests/integration/test_planning_writes.py` |
| 9 | **Bank sync** | Say what happens to this feature when new transactions arrive (most figures are computed on read; `apply_rules` runs on sync). | per-feature tests |
| 10 | **Home and owning tab** | If Home summarises it, the figure is owned by the tab its card links to. | review |
| 11 | **UI route and navigation** | New page added to `ui/src/App.tsx`, nav or user menu, and `ui/scripts/visual-check.mjs`. | `.github/scripts/check_feature_docs.py` (routes documented) |
| 12 | **Tests** | API (`api/tests`), UI (`*.test.ts(x)`), MCP (`api/mcp/tests`) as relevant; test first. | CI `required` job |
| 13 | **Docs** | This folder, `CLAUDE.md` if a convention changed, `api/mcp/README.md` for tools. | `.github/scripts/check_feature_docs.py` |

## Keeping these docs live

`.github/scripts/check_feature_docs.py` runs in CI on every PR (the
`workflows` job in `.github/workflows/test.yml`). It fails when:

- an API route, database table, MCP tool or UI route exists in code but no
  feature doc names it in backticks (`` `GET /api/v1/budgets` ``,
  `` `budgets` ``, `` `list_budgets` ``, `` `/insights` ``);
- a feature doc names an API route that no longer exists;
- a feature doc has no `## Touchpoints` section.

Run it locally with `python3 .github/scripts/check_feature_docs.py .`
(self-test: `python3 .github/scripts/test_check_feature_docs.py`).

It can only check names, not meaning. When you change behaviour, also update
the prose and the touchpoints of every feature doc that mentions what you
changed.
