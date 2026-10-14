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
`finance:budgets.write`. The consent page ticks rules by default; planning,
sync and budgets are opt-in. A refresh never widens scopes.

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
| `set_budgets` | write (budgets) | `POST /api/v1/planning/budgets/set` |
| `pause_budget` | write (budgets) | `POST /api/v1/planning/budgets/{budget_id}/pause` |
| `resume_budget` | write (budgets) | `POST /api/v1/planning/budgets/{budget_id}/resume` |
| `remove_budget` | write (budgets) | `POST /api/v1/planning/budgets/{budget_id}/remove` |

Liabilities (loans, finance, BNPL) reach Claude only as part of the
`net_worth` figure and `liabilities_total` in `cashflow_summary` (T-10-7b),
which `finance:read` already covers (a test pins `liabilities_total` as the
only liability field). No tool reads or writes `/api/v1/liabilities` (web
only). `update_commitment` and `dismiss_commitment` get 409 on a commitment
that carries a loan's repayment (T-10-8), so Claude can't dismiss it to
raise safe-to-spend.

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
