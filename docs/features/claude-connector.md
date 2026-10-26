# Claude connector (MCP server and OAuth)

Users connect Claude to nilu. as a remote MCP server at `/mcp`. The API is
the OAuth 2.1 authorization server: public clients register dynamically,
PKCE S256 is required, access tokens are audience-bound `mcp_access` JWTs
(1 hour, carrying the encrypted data key), refresh tokens rotate (reuse
revokes the grant), and grants expire after 30 idle days. Locally the server
also runs over stdio with the user's password.

## Code

**API** (`api/app/routers/oauth.py`):

| Route | Auth |
|---|---|
| `GET /.well-known/oauth-authorization-server` | public, no `/api/v1` prefix |
| `POST /api/v1/oauth/register` | public, 20/hour per IP |
| `GET /api/v1/oauth/authorize/details` | public |
| `POST /api/v1/oauth/authorize` | `CurrentUser` (needs the session DEK) |
| `POST /api/v1/oauth/token` | public form body |
| `GET /api/v1/oauth/token-info` | the MCP bearer token itself (used by the MCP server) |

**Scopes** (`core/oauth_tokens.py`): `finance:read` (always),
`finance:rules.write`, `finance:planning.write`, `finance:sync`,
`finance:budgets.write`, `finance:rules.edit`. The consent page ticks rules
by default; planning, sync, budgets and editing existing rules are opt-in. A
refresh never widens scopes.

**Tables**: `oauth_clients`, `oauth_authorization_codes`, `oauth_grants`
(DEK wrapped under the code, then under each refresh token).

**MCP server** (`api/mcp/server.py`, own image and deps): every tool needs
`finance:read`; write tools also check their scope.

| Tool | Kind | Calls |
|---|---|---|
| `cashflow_summary` | read | `GET /api/v1/analytics/summary` |
| `forecast` | read | `GET /api/v1/analytics/forecast` |
| `spending` | read | `GET /api/v1/analytics/spending` |
| `spending_trend` | read | `GET /api/v1/analytics/spending/trend` |
| `commitments` | read | `GET /api/v1/analytics/commitments` |
| `accounts` | read | `GET /api/v1/banking/accounts` |
| `sync_status` | read | `GET /api/v1/banking/sync-status` |
| `refresh_banks` | sync | `POST /api/v1/banking/sync` |
| `recent_transactions` | read | `GET /api/v1/banking/transactions` |
| `search_transactions` | read | `POST /api/v1/banking/transactions/search` |
| `rules` | read | `GET /api/v1/rules` |
| `rule_impact` | read | `GET /api/v1/rules/impact` |
| `preview_rule` | read | `POST /api/v1/rules/preview` |
| `create_rule_pack` | write (rules) | `POST /api/v1/rules/packs/bulk` |
| `list_planned_events` | read | `GET /api/v1/planning/planned-events` |
| `add_planned_event` | write (planning) | `POST /api/v1/planning/planned-events` |
| `remove_planned_event` | write (planning) | `POST /api/v1/planning/planned-events/{item_id}/remove` |
| `update_commitment` | write (planning) | `POST /api/v1/planning/commitments/{commitment_id}/update` |
| `dismiss_commitment` | write (planning) | `POST /api/v1/planning/commitments/{commitment_id}/dismiss` |
| `list_budgets` | read | `GET /api/v1/budgets` |
| `list_holdings` | read | `GET /api/v1/holdings` |
| `set_budgets` | write (budgets) | `POST /api/v1/planning/budgets/set` |
| `pause_budget` | write (budgets) | `POST /api/v1/planning/budgets/{budget_id}/pause` |
| `resume_budget` | write (budgets) | `POST /api/v1/planning/budgets/{budget_id}/resume` |
| `remove_budget` | write (budgets) | `POST /api/v1/planning/budgets/{budget_id}/remove` |

The reads that decrypt the whole ledger are limited per user, never per IP
(every MCP call arrives from one address): summary, forecast, spending and
its trend (`rate_limit.LIMITS`, 120 a minute each), rules preview and impact,
the transactions list and search (T-12-10b).

**Holdings (T-11-7, sec T-11-7):** `list_holdings` (read-only, no inputs,
one fixed path) returns at most 100 holdings (`count`, `truncated`), each
with exactly `id`, `name`, `kind`, `value` (today; debts negative),
`value_as_of`, `growth_pct` (null when the user set none), `monthly_contribution`, `linked` and
`projected` at `1y`/`5y`/`10y` from the holding engine
(`services/holdings/listing.py`); no user id, history, commitment ids or
timestamps (`test_holdings_list_api.py` pins the keys). Debts are not
listed (loans, legacy debt assets, anything worth less than nothing; sec /
lead 2026-10-15), so no lender name reaches Claude; names are still user
text, so the tool says they are data, not instructions. `cashflow_summary` also carries `investments_total`, the value
today of the owner D1 investment kinds, the same set and value as net
worth's Investments. Liabilities otherwise reach Claude only as part of
`net_worth` and `liabilities_total` (T-10-7b). No tool reads or writes
`/api/v1/liabilities` (web only). `update_commitment` and `dismiss_commitment` get 409 on a commitment
that carries a loan's repayment (T-10-8), so Claude can't dismiss it to
raise safe-to-spend.

`forecast` events from a commitment carry its `commitment_id` (an id the
`commitments` tool already returns; null on other events), so the UI can
name a loan's linked bill without matching labels. The "{lender} loan
payment" wording is built in the browser and never reaches Claude.
`test_forecast_event_commitment_id.py` pins the exact event keys Claude
receives (`label`, `amount`, `kind`, `commitment_id`) for every kind.

`cashflow_summary` also carries `total_owed` (cards owed + `liabilities_total`,
one aggregate, T-10-14a) and, on each credit account, `statement`:
`statement_balance`, `due_date`, `paid`, `missing` (null when none is
entered; no statement id or source; absent on other roles). sec accepted
these under `finance:read` (2026-10-15, option A);
`tests/integration/test_summary_statement_total_owed.py` pins the exact key
set Claude receives, top level and per account.

**UI**: `/oauth/authorize` (`OAuthConsentPage`), `oauth/ConsentScopes`,
`lib/oauthConsent.ts`; landing-page `AiAssistantSection` and `lib/mcp.ts`.

**Tests**: `api/tests/integration/test_oauth.py`,
`test_budgets_consent.py`, `test_planning_write_auth.py`,
`test_framework_contract.py`; `api/tests/unit/test_oauth_crypto.py`;
`api/mcp/tests/*` (`test_tool_annotations.py` pins the exact tool set);
UI `ConsentScopes.test.tsx`, `oauthConsent.test.ts`, `mcp.test.ts`.

**Adding a tool**: give the API route the narrowest dependency (see
`CLAUDE.md`), route Claude writes through the write framework
([claude-changes.md](claude-changes.md)), add the tool with annotations, add
it to the reviewed set in `test_tool_annotations.py`, to `api/mcp/README.md`
and to the table above.

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `oauth_clients`, `oauth_authorization_codes`, `oauth_grants`. |
| 2 Purge | Grants revoked, codes deleted; clients kept (not per user). |
| 3 Deletion | Grants and codes cascade from `users`. |
| 4 Demo mode | `/oauth/authorize/details` is `UNSAMPLED_BY_DESIGN`. |
| 5 Ownership | Routes Claude calls with account ids check them. |
| 6 Scopes | This feature defines them. |
| 7 Claude tools | This feature. |
| 8 Audit | Writes go through the write framework, except `create_rule_pack`. |
| 9 Bank sync | `refresh_banks`. |
| 10 Home | Landing page section only. |
| 11 UI routes | `/oauth/authorize`. |
| 12 Tests | listed above. |
| 13 Docs | `api/mcp/README.md` (stale, see gaps), `CLAUDE.md`. |
