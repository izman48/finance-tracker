# Finance Tracker

Personal finance insights from Open Banking data. Understand where your money goes, detect recurring payments, and calculate opportunity costs.

## Features (Planned)

- **Bank Connection** - Connect via TrueLayer Open Banking
- **Spending Analysis** - Categorize and visualize transactions
- **Recurring Payments** - Automatically detect subscriptions
- **Opportunity Cost** - Calculate what spending could have become if invested

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

3. **Run database migrations**

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

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| POST | `/api/v1/auth/register` | Register user |
| POST | `/api/v1/auth/login` | Login (OAuth2) |
| GET | `/api/v1/auth/me` | Current user info |

## Security Considerations

- Passwords hashed with bcrypt
- JWT tokens for authentication
- CORS restricted to known origins
- Non-root Docker user
- Database connection pooling with health checks
- Environment-based configuration

## Sprint Progress

### Sprint 1 ✅

- [x] Docker setup
- [x] Database schema
- [x] User authentication
- [x] React scaffold
- [x] Basic tests

### Sprint 2 (Next)

- [ ] TrueLayer OAuth flow
- [ ] Account sync
- [ ] Transaction import

## License

MIT
