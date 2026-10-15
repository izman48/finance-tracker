# TrueLayer Open Banking Integration Guide

## Overview

nilu. connects UK banks through TrueLayer Open Banking: you connect your
accounts, it syncs balances and transactions, and everything is stored
encrypted under your own key.

## Setup

Create an app in the [TrueLayer console](https://console.truelayer.com/) and
put **your own** sandbox credentials in `.env` (never commit them):

```bash
TRUELAYER_CLIENT_ID=<your sandbox client id>
TRUELAYER_CLIENT_SECRET=<your sandbox client secret>
TRUELAYER_REDIRECT_URI=http://localhost:8000/api/v1/banking/callback
TRUELAYER_SANDBOX=true
```

Register the same redirect URI in the console.

## Available Endpoints

### 1. Check Connection Status
```bash
GET /api/v1/banking/status
Authorization: Bearer <your_jwt_token>
```

**Response:**
```json
{
  "is_connected": true,
  "connections_count": 1,
  "last_synced_at": "2026-10-15T08:30:00+00:00",
  "connections": [
    {"id": "uuid", "provider_name": "Mock Bank", "is_expired": false,
     "expires_at": "2027-01-13T08:30:00+00:00", "last_synced_at": "2026-10-15T08:30:00+00:00"}
  ],
  "message": "1 bank(s) connected"
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
  "days": 88
}
```

The first sync after connecting fetches up to two years (banks allow more than
90 days only in the first minutes after consent). Every later sync fetches the
last 88 days, whatever `days` asks for. One sync per user runs at a time.

**Response:**
```json
{
  "transactions_synced": 147,
  "message": "Successfully synced 147 new transaction(s) from 1 bank(s) (last 88 days)"
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
In the app at http://localhost:5173: **Wealth → Connect a bank** (or Cashflow
when you have no accounts). Accounts appear on Cashflow and Wealth,
transactions under Spending. "Sync now" on Cashflow refreshes.

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

Amounts, descriptions, merchants, account names and balances are encrypted
under your key; dates, categories, account types and the bank's own reference
numbers stay plain (the privacy page lists every unencrypted field).

## Token Management

- **Access token:** valid for about an hour; **refresh token:** used to get a new one.
- Both are stored encrypted under your key, so they can only be used during a
  request you make (there is no background sync). An expired access token is
  refreshed during the next sync.
- Disconnecting a bank, or deleting your account, ends the connection at
  TrueLayer as well as deleting the tokens.

## Troubleshooting

**Connection fails:**
- Check that redirect URI matches in TrueLayer console
- Verify credentials in `.env` are correct
- Check API logs: `docker compose logs api`

**Token expired or consent lapsed:**
- The next sync refreshes an expired access token.
- When the bank's consent has expired (usually 90 days), the app shows
  "Reconnect"; reconnect via `/banking/connect`.

**No transactions syncing:**
- Ensure accounts are synced first
- Check that accounts have transactions in the date range
- Sandbox accounts have limited mock data

## API Documentation

Full interactive API docs: http://localhost:8000/api/docs

All banking endpoints require authentication with a JWT token.
