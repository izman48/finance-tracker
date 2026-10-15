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
- **Planned expenses & payment plans** — model one-off costs and split purchases into installments; tick "Card payment" on a planned card bill and it counts once with the projected card bills
- **Credit-card modelling** — per-card repayment (statement balance, full balance, fixed, instalments or a schedule), statements, and instalment plans (e.g. Amex Plan It) inside their card
- **Budgets** — monthly limits per category, paced across your pay cycle, with a budget line on the forecast; budgets never change safe to spend
- **Wealth** — net worth from accounts, holdings (ISAs, pensions, property…), loans, mortgages with house equity, and a projection towards a target
- **Rules** — your own categorisation rules and shareable rule packs (regex runs on a linear-time engine)
- **Claude (MCP)** — connect Claude to ask about your money; it reads by default, and any change it makes is previewed, audited, undoable, and never raises safe to spend until you keep it ([api/mcp/README.md](api/mcp/README.md))
- **Demo mode** — "Anonymized" swaps in a synthetic sample account on every screen, sends no API request and blocks writes

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

**Run tests** (the test image copies the source, so rebuild after editing)

```bash
docker compose --profile test build test
docker compose --profile test run --rm test          # API, in parallel on in-memory SQLite
docker compose --profile test run --rm --build mcp-test   # MCP server
cd ui && npm ci && npx vitest run && npm run lint && npm run build
```

**Run specific tests**

```bash
docker compose --profile test run --rm test pytest tests/unit -v
```

**Code formatting**

```bash
docker compose exec api ruff check .
```

See [CLAUDE.md](CLAUDE.md) for conventions, gotchas and the CI wiring, and
[docs/features/](docs/features/) for what each feature touches.

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
- **Per-user encryption**: transactions, account details, amounts, names and bank tokens are encrypted under a key that only the user's password or recovery code unlocks (or a Claude connection they approve, while it is active); the server holds it only during a request. Every unencrypted column is listed in `api/app/core/privacy_plaintext.py` and on the privacy page
- `ENCRYPTION_KEY` (server Fernet key) wraps the session copy of that key in the JWT and protects a few server-side secrets
- `SECRET_KEY` strength enforced at startup in live mode (no placeholder keys)
- OAuth `state` is a signed, short-lived token (CSRF protection)
- Bank connections ended at TrueLayer on disconnect and on account deletion
- Rate limits on login, signup, password routes, Claude's writes and decrypt-heavy reads (per user, since MCP calls share one address)
- Secrets live only in `.env` files (gitignored); `.env.example` is the committed template
- CORS restricted to known origins
- Non-root Docker user
- Database connection pooling with health checks
- Environment-based configuration

### Known tradeoff: JWT storage

The frontend stores the JWT in `localStorage`, which is readable by JavaScript
and therefore vulnerable to token theft if an XSS bug is introduced. This is a
deliberate, documented tradeoff for now. The access-token lifetime is
`ACCESS_TOKEN_EXPIRE_MINUTES` (default 7 days, `60 * 24 * 7`); shorten it to
limit the blast radius. Migrating to httpOnly, SameSite cookies is tracked as a
follow-up.

## Roadmap

- httpOnly cookie auth (see the JWT tradeoff above)
- Statement-balance precision and seasonal/one-off awareness for longer forecasts

## License

MIT
