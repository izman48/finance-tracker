# Quick start

Run nilu. locally with Docker and connect a TrueLayer sandbox bank.

## 1. Start the stack

```bash
cp .env.example .env      # then fill in the values it asks for
docker compose up -d      # api :8000, ui :5173, db :5433 (all on 127.0.0.1)
```

Migrations run when the API container starts.

- App: http://localhost:5173
- API docs: http://localhost:8000/api/docs
- Health: http://localhost:8000/api/v1/health (503 if the database is down)

## 2. Create your account

There are no built-in users. Open the app, choose **Get started**, and create an account
with any email and a password of 8 or more characters. The app then shows a
**recovery code once**: keep it. Your data is encrypted under a key that only
your password or that code unlocks, so a password reset without the code
deletes your encrypted data.

## 3. Connect a sandbox bank

Set `TRUELAYER_CLIENT_ID` / `TRUELAYER_CLIENT_SECRET` from your own TrueLayer
console (sandbox) in `.env` first (see [TRUELAYER_GUIDE.md](TRUELAYER_GUIDE.md)).

1. Go to **Wealth** and choose **Connect a bank** (Cashflow offers it too when
   you have no accounts).
2. Pick a sandbox provider (e.g. Mock Bank) and sign in with its test
   credentials.
3. Back in the app, accounts and up to two years of transactions sync. Later
   syncs ("Sync now" on Cashflow) fetch the last 88 days.

## 4. Find your way around

Four tabs:

- **Home** — one summary card per tab: safe to spend, coming up, spending,
  net worth and what you owe.
- **Cashflow** — safe to spend, the balance forecast (with your budgets as a
  dotted line), coming up, nudges, and your accounts. **Commitments** (bills,
  income, planned items) is a page off Cashflow.
- **Spending** — where the money went, by month, category and merchant, plus
  budgets and the transaction list.
- **Wealth** — the balance sheet: accounts, cards (with statements and
  instalment plans), holdings, loans and mortgages, and a projection.

The user menu has **Rules**, **Changes made by Claude**, **Privacy** and
**Anonymize numbers** (demo mode: a synthetic sample account, no API
requests, writes blocked; useful for screenshots). To connect Claude, see the
landing page's Claude section or [api/mcp/README.md](api/mcp/README.md).

## 5. Use the API directly

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=you@example.com&password=YOUR_PASSWORD" | jq -r .access_token)

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/banking/status
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/analytics/summary
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/banking/transactions?page=1&page_size=20"
```

The token carries your session's encryption key, so every data route needs
it. Full reference: http://localhost:8000/api/docs.

## Troubleshooting

- **Blank page at :5173 with no console error**: a stale container. Restart
  Docker, then `docker compose up -d --build`.
- **`UndefinedColumn` errors after pulling**: the code is ahead of the schema;
  `docker compose restart api` runs the new migrations.
- **Bank connection fails**: check the redirect URI in `.env` matches the one
  registered in the TrueLayer console, and that you're using sandbox
  credentials with the sandbox environment.
- **Logs**: `docker compose logs -f api` (or `ui`, `db`).

## Next

- Tests and conventions: [README.md](README.md) and [CLAUDE.md](CLAUDE.md).
- What each feature touches: [docs/features/](docs/features/).
- Claude (MCP): [api/mcp/README.md](api/mcp/README.md).
- Production: [DEPLOY.md](DEPLOY.md).
