# Finance Tracker - Quick Start Guide

## Your App is Now Running! 🎉

### Access URLs

- **Frontend (React UI):** http://localhost:5173
- **Backend API Docs:** http://localhost:8000/api/docs
- **Database:** localhost:5433

### Test Credentials

```
Email: test@example.com
Password: testpassword123
```

## How to Use the App

### Step 1: Login
1. Open http://localhost:5173 in your browser
2. Click "Login" in the navigation
3. Enter the test credentials above

### Step 2: Connect Your Bank (Sandbox)
1. After logging in, you'll see the Dashboard
2. Click the **"Connect Bank Account"** button
3. A new window will open with TrueLayer's sandbox authorization
4. Select any test bank (e.g., "Mock Bank")
5. Login with any credentials (sandbox accepts anything)
6. Select which accounts to connect
7. Click "Allow" to authorize

### Step 3: Wait for Sync
After authorization:
- The app will automatically sync your bank accounts
- Then it will sync transactions (last 90 days)
- You'll see success messages at the top of the dashboard
- Your accounts will appear with balances

### Step 4: Explore Your Data
- View all connected accounts with current balances
- Click "Sync Accounts" to refresh balances
- Click "Sync Transactions" to pull latest transactions

## What You Can See

### Dashboard Features

✅ **Bank Connection Status**
- See if your bank is connected
- Token expiration time
- One-click reconnection if needed

✅ **Account Cards**
- All your connected accounts
- Current and available balances
- Last updated timestamp
- Account type (Current, Savings, Credit Card)

✅ **Sync Controls**
- Manually refresh account balances
- Pull new transactions
- Real-time status updates

✅ **Cashflow & safe-to-spend**
- "Safe to spend" — your cash minus what's committed before next payday
- Overdraft shown as a separate cushion; net worth and what's "owed (scheduled)"
- A **balance forecast** graph (payday / 30d / 90d / 6mo / 1yr) with the low point flagged
- Per-account setup: mark accounts as spending/savings/credit, set overdraft limits, and configure credit-card repayment (full balance, or pay-down installments like Monzo Flex)

### Navigation
- **Dashboard** — safe-to-spend, forecast graph, planned expenses, accounts
- **Spending** — where it went: month-by-month trend + category/merchant breakdown (transfers & card payments filtered out)
- **Commitments** — review auto-detected recurring income/bills (confirm/edit/dismiss) and add one-off or manual items
- **Transactions** — full list; mark any transaction as recurring with one click

## Testing with Sandbox Data

The app is configured with TrueLayer Sandbox, which provides:
- **Mock banks** with realistic test data
- **Sample transactions** spanning several months
- **Different account types** (Current, Savings, Credit Cards)
- **Various transaction categories** (Shopping, Bills, Travel, etc.)

### Common Sandbox Banks
- Mock Bank
- Lloyds Bank (Sandbox)
- Barclays (Sandbox)
- HSBC (Sandbox)
- Monzo (Sandbox)

All accept any credentials in sandbox mode!

## API Endpoints (For Developers)

You can also interact with the API directly:

### Get an Auth Token
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=testpassword123"
```

### Check Bank Status
```bash
curl -X GET http://localhost:8000/api/v1/banking/status \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### View All Accounts
```bash
curl -X GET http://localhost:8000/api/v1/banking/accounts \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### View Transactions
```bash
curl -X GET "http://localhost:8000/api/v1/banking/transactions?page=1&page_size=20" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Full interactive API documentation: http://localhost:8000/api/docs

## Common Issues

### "Connect Bank Account" button does nothing
- Check browser console for errors
- Verify API is running: `docker compose ps`
- Check API logs: `docker compose logs api`

### Bank connection fails
- Ensure you completed the full OAuth flow
- Try disconnecting popup blockers
- Check that redirect URI is correct in `.env`

### No accounts appearing
- Click "Sync Accounts" manually
- Check you authorized at least one account
- Verify in API docs that `/banking/accounts` returns data

### Transactions not syncing
- Ensure accounts are synced first
- Click "Sync Transactions" manually
- Sandbox accounts may have limited test data

## Docker Commands

```bash
# View all logs
docker compose logs -f

# View specific service logs
docker compose logs -f api
docker compose logs -f ui

# Restart a service
docker compose restart api
docker compose restart ui

# Stop everything
docker compose down

# Start everything
docker compose up -d

# Rebuild and restart
docker compose up -d --build
```

## What's Next?

Now that you have transaction data flowing in, you can build:

1. **Spending Analytics**
   - Category breakdown charts
   - Monthly spending trends
   - Merchant analysis
   - Budget vs actual

2. **Recurring Payment Detection**
   - Identify subscriptions (Netflix, Spotify, etc.)
   - Calculate total recurring costs
   - Find forgotten subscriptions
   - Predict future spending

3. **Opportunity Cost Calculator**
   - "What if I invested instead?"
   - Compare with S&P 500 returns
   - Show compound growth over time
   - Motivate better spending habits

4. **Smart Insights**
   - Unusual spending alerts
   - Savings recommendations
   - Bill payment reminders
   - Financial health score

## Project Structure

```
finance-tracker/
├── api/                    # FastAPI backend
│   ├── app/
│   │   ├── core/          # Config, database, security
│   │   ├── models/        # SQLAlchemy models
│   │   ├── routers/       # API endpoints
│   │   │   ├── auth.py    # User auth
│   │   │   ├── banking.py # Open Banking (NEW!)
│   │   │   └── health.py  # Health checks
│   │   ├── schemas/       # Pydantic schemas
│   │   └── services/      # Business logic
│   │       └── truelayer.py # Open Banking service (NEW!)
│   └── migrations/        # Database migrations
├── ui/                     # React + TypeScript
│   └── src/
│       ├── pages/
│       │   └── DashboardPage.tsx # Updated with banking!
│       └── services/
│           └── api.ts      # Updated with banking API
└── docker-compose.yml
```

## Support

- **API Docs:** http://localhost:8000/api/docs
- **TrueLayer Guide:** See `TRUELAYER_GUIDE.md`
- **Logs:** `docker compose logs -f`

Happy tracking! 🚀
