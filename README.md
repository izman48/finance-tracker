# Finance Tracker

Know what's really yours to spend. Finance Tracker connects to your bank via
TrueLayer Open Banking and turns the raw data into one cashflow projection — a
trustworthy "safe to spend" figure, a balance forecast, and clear spending insight.

## Features

- **Bank connection** — connect UK banks & cards via TrueLayer Open Banking
- **Safe to spend** — cash minus what's committed before your next payday (credit cards kept separate, overdraft shown as a cushion)
- **Balance forecast** — project your balance up to a year out; see the low point and any overdraft breach
- **Commitments** — auto-detect recurring income/bills and confirm once; add one-off or manual items, or mark any transaction recurring
- **Spending** — where your money goes by month / category / merchant, split credit-vs-cash, with internal transfers and card repayments filtered out
- **Planned expenses & payment plans** — model one-off costs and split purchases into installments (e.g. Monzo Flex)
- **Credit-card modelling** — per-card repayment: full balance (e.g. Amex) or pay-down installments

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: React 18, TypeScript, Vite, TailwindCSS
- **Infrastructure**: Docker, Docker Compose

## Getting Started

### Prerequisites

- Docker and Docker Compose
- (Optional) TrueLayer account for bank connections

### Setup

1. **Clone and configure**

```bash
cp .env.example .env
# Edit .env with your settings
```

2. **Start services**

```bash
docker compose up --build
```

3. **Database migrations**

Migrations run automatically when the API container starts. To run them manually:

```bash
docker compose exec api alembic upgrade head
```

4. **Access the app**

- UI: http://localhost:5173
- API Docs: http://localhost:8000/api/docs
- Health Check: http://localhost:8000/api/v1/health

### Development

**Run tests**

```bash
docker compose run --rm test
```

**Run specific tests**

```bash
docker compose exec api pytest tests/unit -v
docker compose exec api pytest tests/integration -v
```

**Code formatting**

```bash
docker compose exec api black .
docker compose exec api ruff check .
```

## Project Structure

```
finance-tracker/
├── api/                    # Python FastAPI backend
│   ├── app/
│   │   ├── core/          # Config, database, security
│   │   ├── models/        # SQLAlchemy models
│   │   ├── routers/       # API endpoints
│   │   ├── schemas/       # Pydantic schemas
│   │   └── services/      # Business logic
│   ├── migrations/        # Alembic migrations
│   └── tests/
│       ├── unit/
│       └── integration/
├── ui/                     # React frontend
│   └── src/
│       ├── components/
│       ├── hooks/
│       ├── pages/
│       └── services/
└── docker-compose.yml
```

## API Endpoints

Full interactive docs at `http://localhost:8000/api/docs`. Main groups:

| Group | Examples |
|-------|----------|
| Auth | `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me` |
| Banking | `GET /api/v1/banking/connect`, `GET /api/v1/banking/callback`, `POST /api/v1/banking/sync/{accounts,transactions}`, `GET /api/v1/banking/transactions` |
| Analytics | `GET /api/v1/analytics/summary` (safe-to-spend), `/analytics/forecast`, `/analytics/spending`, `/analytics/spending/trend`, `GET/POST/PATCH /analytics/commitments`, `POST /analytics/planned-items` |

## Security Considerations

- Passwords hashed with bcrypt; minimum length enforced on registration
- JWT tokens for authentication
- Bank OAuth tokens encrypted at rest (Fernet) via `ENCRYPTION_KEY`
- `SECRET_KEY` strength enforced at startup in live mode (no placeholder keys)
- OAuth `state` is a signed, short-lived token (CSRF protection)
- Bank tokens revoked at TrueLayer on disconnect
- Secrets live only in `.env` files (gitignored); `.env.example` is the committed template
- CORS restricted to known origins
- Non-root Docker user
- Database connection pooling with health checks
- Environment-based configuration

### Known tradeoff: JWT storage

The frontend stores the JWT in `localStorage`, which is readable by JavaScript
and therefore vulnerable to token theft if an XSS bug is introduced. This is a
deliberate, documented tradeoff for now; the access-token lifetime is kept short
(`ACCESS_TOKEN_EXPIRE_MINUTES`, default 30) to limit the blast radius. Migrating
to httpOnly, SameSite cookies is tracked as a follow-up.

## Roadmap

- Savings goals (fund toward a target with a safe-to-add amount)
- httpOnly cookie auth (see the JWT tradeoff above)
- Statement-balance precision and seasonal/one-off awareness for longer forecasts

## License

MIT
