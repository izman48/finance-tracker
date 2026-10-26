# Bank connections (TrueLayer)

Users link UK banks through TrueLayer open banking, renew a lapsed 90-day
consent, and disconnect one bank or all of them (which deletes those accounts
and transactions).

## Code

**API** (`api/app/routers/banking.py`):

| Route | Auth | Notes |
|---|---|---|
| `GET /api/v1/banking/connect` | `CurrentUser` | Returns the TrueLayer auth URL; the signed `oauth_state` carries the encrypted DEK. |
| `GET /api/v1/banking/connections/{connection_id}/reconnect` | `CurrentUser` | Auth URL pre-selecting the provider. |
| `GET /api/v1/banking/callback` | signed state | Exchanges the code, upserts the connection by provider, runs the first accounts sync and a 730-day history sync, redirects to `/dashboard?bank_connected=…`. |
| `GET /api/v1/banking/status` | `CurrentUser` | Per-connection expiry and last sync. |
| `POST /api/v1/banking/disconnect` | `CurrentUser` | Revokes each access token (best effort), deletes every connection. |
| `DELETE /api/v1/banking/connections/{connection_id}` | `CurrentUser` | Same for one connection. |

**Tables**: `bank_connections` (encrypted `provider_id`, `provider_name`,
`access_token`, `refresh_token`; plaintext `token_expires_at`,
`last_synced_at`). Cascades to `accounts`.

**Services**: `services/truelayer.py` (auth link, token exchange and refresh,
`revoke_connection`: TrueLayer's delete-connection call, refreshing once on 401; `ReauthRequired` on `invalid_grant`), `core/security.py`
(`create_oauth_state`), `core/psu_ip.py`.

**UI**: Wealth (`NetWorthPage`: connect, reconnect, sync, disconnect all),
Home first-run panel (`OverviewPage`), Cashflow (`DashboardPage` handles
`?bank_connected=`), `/callback` (`CallbackPage`, a frontend fallback only).

**Tests**: `api/tests/integration/test_bank_reauth.py`,
`test_callback_logs.py`, `test_psu_ip_header.py`, `test_oauth.py` (MCP
refused).

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | `bank_connections`. |
| 2 Purge | Yes (no TrueLayer revoke: tokens can't be decrypted). |
| 3 Deletion | Explicitly deleted by delete-account, after each connection is ended at TrueLayer (`revoke_connection`, best-effort, capped at `REVOKE_TOTAL_SECONDS`; a connection whose tokens can't be decrypted is skipped, and deletion still completes). See [data-lifecycle.md](data-lifecycle.md). Not yet verified against the TrueLayer sandbox ([known-gaps](../known-gaps.md)). |
| 4 Demo mode | `/banking/status` served. `/banking/connect` and reconnect are `UNSAMPLED_BY_DESIGN`. |
| 5 Ownership | Connection ids are checked inline by `user_id`. |
| 6 Scopes | Web only, and must stay so. |
| 7 Claude tools | none, by design. |
| 8 Audit | n/a. |
| 9 Bank sync | The callback runs the first sync. |
| 10 Home | First-run "Connect bank" panel. Owned by Wealth. |
| 11 UI routes | `/callback`. |
| 12 Tests | listed above; no functional test of disconnect (gap). |
| 13 Docs | `TRUELAYER_GUIDE.md` (partly stale). |
