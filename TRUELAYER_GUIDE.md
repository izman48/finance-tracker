# TrueLayer Open Banking Integration Guide

## Overview

Your finance tracker now has full Open Banking integration via TrueLayer! You can connect your bank accounts, sync transactions, and analyze your spending.

## Current Setup

Your app is configured with **TrueLayer Sandbox** credentials for testing:
- Client ID: `sandbox-plutus-2e2a27`
- Environment: Sandbox (test data)
- Redirect URI: `http://localhost:8000/api/v1/banking/callback`

## Available Endpoints

### 1. Check Connection Status
```bash
GET /api/v1/banking/status
Authorization: Bearer <your_jwt_token>
```

**Response:**
```json
{
  "is_connected": false,
  "is_expired": false,
  "expires_at": null,
  "message": "No bank connection"
}
```

### 2. Get Bank Connection URL
```bash
GET /api/v1/banking/connect
Authorization: Bearer <your_jwt_token>
```

**Response:**
```json
{
  "auth_url": "https://auth.truelayer-sandbox.com?response_type=code&...",
  "message": "Visit this URL to connect your bank account..."
}
```

### 3. Sync Bank Accounts
```bash
POST /api/v1/banking/sync/accounts
Authorization: Bearer <your_jwt_token>
```

**Response:**
```json
{
  "accounts_synced": 3,
  "accounts": [
    {
      "id": "uuid",
      "provider_name": "Mock Bank",
      "account_type": "TRANSACTION",
      "display_name": "Current Account",
      "currency": "GBP",
      "current_balance": 1250.50,
      "available_balance": 1200.00
    }
  ],
  "message": "Successfully synced 3 account(s)"
}
```

### 4. Sync Transactions
```bash
POST /api/v1/banking/sync/transactions
Authorization: Bearer <your_jwt_token>
Content-Type: application/json

{
  "days": 90
}
```

**Response:**
```json
{
  "transactions_synced": 147,
  "message": "Successfully synced 147 new transaction(s) from the last 90 days"
}
```

### 5. Get All Accounts
```bash
GET /api/v1/banking/accounts
Authorization: Bearer <your_jwt_token>
```

### 6. Get Transactions (Paginated)
```bash
GET /api/v1/banking/transactions?page=1&page_size=50&account_id=<optional>
Authorization: Bearer <your_jwt_token>
```

**Response:**
```json
{
  "items": [...],
  "total": 147,
  "page": 1,
  "page_size": 50
}
```

## How to Connect Your Bank (Sandbox Testing)

1. **Login to your account:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=test@example.com&password=testpassword123"
   ```

2. **Get the bank connection URL:**
   ```bash
   curl -X GET http://localhost:8000/api/v1/banking/connect \
     -H "Authorization: Bearer <your_token>"
   ```

3. **Visit the `auth_url` in your browser:**
   - The sandbox will show a mock bank selection screen
   - Choose any test bank (e.g., "Mock Bank")
   - Login with any credentials (sandbox accepts anything)
   - Authorize access to your accounts

4. **After authorization:**
   - You'll be redirected back to `http://localhost:5173/dashboard?bank_connected=true`
   - Your TrueLayer access tokens are now saved

5. **Sync your accounts:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/banking/sync/accounts \
     -H "Authorization: Bearer <your_token>"
   ```

6. **Sync your transactions:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/banking/sync/transactions \
     -H "Authorization: Bearer <your_token>" \
     -H "Content-Type: application/json" \
     -d '{"days": 90}'
   ```

## Using Real Banks (Production)

To connect real bank accounts:

1. **Get Production Credentials:**
   - Go to https://console.truelayer.com/
   - Create a production application
   - Get your production Client ID and Secret

2. **Update `.env` file:**
   ```env
   TRUELAYER_CLIENT_ID=your-production-client-id
   TRUELAYER_CLIENT_SECRET=your-production-secret
   TRUELAYER_REDIRECT_URI=https://yourdomain.com/api/v1/banking/callback
   ```

3. **Update `app/core/config.py`:**
   ```python
   truelayer_sandbox: bool = False  # Set to False for production
   ```

4. **Restart the application:**
   ```bash
   docker compose restart api
   ```

## Testing the Integration

### Via API Documentation
Visit http://localhost:8000/api/docs and test the endpoints interactively:

1. Click "Authorize" button
2. Login to get a JWT token
3. Try the banking endpoints under the "banking" section

### Via Frontend
The React app at http://localhost:5173 should have:
- A "Connect Bank" button in the dashboard
- Account list display
- Transaction history view

## What Data Gets Synced

### Accounts
- Account ID (external reference)
- Provider/Bank name
- Account type (Current, Savings, Credit Card)
- Display name
- Currency
- Current balance
- Available balance
- Last updated timestamp

### Transactions
- Transaction ID (external reference)
- Type (DEBIT/CREDIT)
- Amount
- Currency
- Description
- Merchant name
- Category (auto-categorized by TrueLayer)
- Transaction date

## Token Management

- **Access Token:** Valid for ~1 hour
- **Refresh Token:** Used to get new access tokens
- **Auto-refresh:** The service automatically refreshes expired tokens

## Next Steps

Now that Open Banking is integrated, you can build:

1. **Spending Analytics:**
   - Category breakdown
   - Monthly spending trends
   - Top merchants

2. **Recurring Payment Detection:**
   - Identify subscriptions
   - Calculate total recurring costs
   - Detect missed payments

3. **Opportunity Cost Calculator:**
   - Show what spending could have become if invested
   - Compare against S&P 500, index funds, etc.
   - Long-term wealth projections

4. **Budget Tracking:**
   - Set category budgets
   - Alert on overspending
   - Savings goals

## Troubleshooting

**Connection fails:**
- Check that redirect URI matches in TrueLayer console
- Verify credentials in `.env` are correct
- Check API logs: `docker compose logs api`

**Token expired:**
- Call `/banking/sync/accounts` - it auto-refreshes
- Or reconnect via `/banking/connect`

**No transactions syncing:**
- Ensure accounts are synced first
- Check that accounts have transactions in the date range
- Sandbox accounts have limited mock data

## API Documentation

Full interactive API docs: http://localhost:8000/api/docs

All banking endpoints require authentication with a JWT token.
