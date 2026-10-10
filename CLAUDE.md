# CLAUDE.md

Guidance for working in this repo. Keep it current when conventions change.

## What this is

A personal-finance app: connect UK banks via **TrueLayer** open banking, then
surface a trustworthy "safe to spend" figure, a balance forecast, spending
insight, commitments, and net worth. The deployed product is branded **nilu.**

- **Backend**: `api/` — Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, Alembic.
- **Frontend**: `ui/` — React 18 + TypeScript + Vite + TailwindCSS, Recharts, GSAP.
- **Infra**: Docker Compose; production fronted by Caddy (auto-HTTPS). CI on push
  to `main` runs tests then deploys.

This repo is meant to be **clonable and deployable by anyone**. Never commit
personal infrastructure (domain, IPs, ssh aliases, account-specific values).
Those live in untracked `.env` / `.env.production` on the server. The product
name "nilu." in the UI is intentional; infra details are not.

The product is heading toward a **paid offering and possible FCA approval**, so
hold a high security bar — treat auth/crypto/banking/PII findings as
ship-blockers and prefer fail-closed designs. Don't claim regulatory status for
nilu. itself in UI/marketing (TrueLayer's FCA authorisation can be cited).

## Layout

```
api/app/
  routers/      auth, banking, analytics, assets, rules, health
  services/     analytics/ (domain package: cadence, commitments, repayments,
                forecast, spending, net_worth, summary — analytics_service.py
                is a compatibility shim), truelayer, categorization,
                email_service
  models/ schemas/ core/   (core: security.py = JWT+hashing, encryption.py = Fernet)
  migrations/   Alembic
  tests/        unit/ + integration/ (pytest)
api/mcp/        MCP server — its own image and deps; stdio locally, streamable
                HTTP when deployed at /mcp (bearer tokens verified by the API)
ui/src/
  pages/        the four tabs — OverviewPage (Home: one summary card per
                tab, each a link into it), DashboardPage (Cashflow),
                SpendingPage, NetWorthPage (Wealth = the balance sheet) —
                plus CommitmentsPage (sub-page off Cashflow), RulesPage
                (user menu), auth pages. HomePage is the marketing landing.
  components/   (components/ui = shared primitives incl. Toast/ConfirmDialog
                providers)  lib/ (format, cadence, assets)  types.ts
                services/api.ts  hooks/
  scripts/visual-check.mjs   browser screenshot harness (BASE_URL overridable)
```

The IA is four tabs (Home / Cashflow / Spending / Wealth); `REDESIGN_PLAN.md`
records the redesign and the still-open extensions (demo mode, theming).

## Commands

**Dev stack** (hot-reloads both api and ui via volume mounts):
```bash
docker compose up -d          # api :8000, ui :5173, db :5433 (host)
```

**API tests**:
```bash
docker compose --profile test build test   # REQUIRED after editing test/source —
docker compose --profile test run --rm test #   the test image COPIES source (no mount)
```
Skipping the rebuild silently runs stale tests (the count won't change). CI
always builds fresh, so this only bites locally.

**MCP server tests** (own image, no db):
```bash
docker compose --profile test run --rm --build mcp-test
```

**Caddy config** (real Caddy image; validates `deploy/Caddyfile`, with and
without an extra static site, checks the served headers, and tests
`deploy/preflight-sites.sh`, which deploy.sh runs before `up`):
```bash
./deploy/test-caddy.sh
```

**Frontend**:
```bash
cd ui
npm run build    # tsc && vite build — run before merging
npm run lint     # eslint, --max-warnings 0
npm run dev      # 127.0.0.1 only; VITE_DEV_LAN=1 npm run dev to test from a phone on your LAN
```
The Docker dev stack publishes the UI on `127.0.0.1:5173` only, for the same reason.

**CI wiring**: every GitHub Action is pinned to a commit SHA, and
`.github/workflows/audit.yml` runs `npm audit --audit-level=high` (dev
dependencies included) and `pip-audit` weekly and on demand. Both are
enforced by `.github/scripts/check_workflows.py` (self-tested by
`test_check_workflows.py`, run in `test.yml`). Pin new actions the same way.

**Visual / mobile check** (dev server must be running):
```bash
cd ui && node scripts/visual-check.mjs   # screenshots every page × 4 viewports
```
It mocks the API and reports console errors and any HTTP ≥400. Use it to verify
UI changes and mobile/iPad layout; screenshots land in `/tmp/ui-shots/`. For a
quick overflow check, navigate a page and compare `document.documentElement
.scrollWidth` to `clientWidth`.

## Gotchas (these have bitten us)

- **Migrations run only at container boot** (`alembic upgrade head` in the api
  command). Code hot-reloads from the mount, so the running code can get *ahead*
  of the schema after you pull new migrations → `UndefinedColumn` 500s. Fix:
  `docker compose restart api` (or `docker exec finance_api alembic upgrade head`).
- **Migrations are additive** (expand first, contract in a later release), so
  the previous release still runs on the new schema. Every migration has a
  working `downgrade()`, and a data migration copies the old values into a
  backup table first. Rolling back a release that added a migration means
  `alembic downgrade` on the server *before* merging the revert; see
  DEPLOY.md "Rollback".
- **Decimal-as-string**: money fields arrive from the API as strings. Coerce with
  `Number(...)` before arithmetic in the UI.
- **Mobile grid overflow**: a bare `grid md:grid-cols-2` gives mobile an *implicit
  auto* track that sizes to max-content and overflows (truncate can't shrink it).
  Always set an explicit base column — `grid grid-cols-1 md:grid-cols-2` — so the
  track is `minmax(0,1fr)`. For truncating flex children, add `min-w-0` to the
  growing item and `shrink-0` to siblings that must keep their width.
- **Credit-card sign differs by provider** (Amex owed = positive, Monzo owed =
  negative). `Account.current_balance` stays raw (it is encrypted, so it can't
  be migrated); read money owed only through
  `app/services/balance_sign.credit_owed`. Positive = owed, negative = card in
  credit. Unverified providers fall back to `abs()` (never hide a debt); add a
  provider to a sign list only once its sign is observed on real data.
- **Client IP behind Caddy**: the auth rate limits key on `request.client.host`,
  which is only the real caller because prod uvicorn runs with
  `--forwarded-allow-ips` set to Caddy's pinned address on the `edge` network
  (`docker-compose.prod.yml`). Drop that flag, or move Caddy off its fixed IP,
  and every user shares one login budget (a lockout DoS). Never set it to `*`,
  and never read `X-Forwarded-For` in app code.

## Conventions

- **Design system**: dark "ink + mint" theme. Reusable classes live in
  `ui/src/index.css` (`.card`, `.card-pad`, `.btn-primary`, `.btn-ghost`,
  `.input`, `.label`, `.chip-*`, `.seg`/`.seg-active`, `.modal-backdrop`/
  `.modal-panel`, `.banner-ok`/`.banner-err`, `.stat-figure`, `.tnum`). Use them
  rather than re-styling. Colors: `accent` (mint) positive, `neg` (rose), `warn`
  (amber for credit), `pos` (green income). Fonts: Inter (body), Space Grotesk
  (`font-display`). Charts use Recharts; motion uses GSAP and must respect
  `prefers-reduced-motion`.
- **Navigation**: four tabs (Home / Cashflow / Spending / Wealth) — desktop
  top-nav at `lg+`; below `lg` (phones *and* iPad portrait) a bottom tab bar.
  Keep that breakpoint consistent. Login lands on Home (`/home`); Home only
  summarises — every figure it shows is owned by the tab its card links to.
  Rules and account management live in the user menu; commitments management
  is a sub-page off Cashflow.
- **Account ids in requests**: any account id a route accepts (path or body,
  e.g. `account_id`, `pay_from_account_id`) goes through `core/ownership.py`
  (`owned_account` / `require_owned_account_ids`) before anything is written;
  foreign and unknown ids both get 404. `tests/integration/test_account_ownership.py`
  walks `app.routes` and fails on a write route with an `*account_id` input that
  has no ownership case, so add one when you add such a route. Both match the
  singular `*account_id` suffix only: name new fields that way (not
  `account_ids` / `accountId`), or extend both.
- **Auth/security**: every API endpoint filters by `current_user` (no IDOR). JWTs
  carry a `typ` claim — `access`, `pwd_reset`, `oauth_state` — and
  `decode_access_token` rejects anything that isn't `access`, so reset/oauth
  tokens can't be replayed as bearer credentials. Passwords are bcrypt. Never
  log secrets or token-bearing URLs (the no-SMTP email fallback only echoes the
  body in non-live mode).
- **Per-user encryption** (`core/user_crypto.py` + `core/encryption.py`):
  transaction text/amounts, account details, and bank tokens are encrypted with
  a per-user DEK the server only holds during a session (Argon2id password-
  wrapped at rest; the JWT `dk` claim carries it, server-Fernet-encrypted, into
  a request contextvar). Consequences to respect: no SQL filtering/aggregation
  on encrypted columns (compute in Python); no background jobs can read bank
  data (sync happens at login/on demand); loading another user's row through an
  un-scoped query raises `InvalidToken` — always scope queries by user; a
  missing session key raises `DEKUnavailableError` → 401 (fail closed).
  Recovery codes are shown once; password reset without one purges bank data
  by design.
- **Remote MCP / OAuth** (`services/oauth.py`, `core/oauth_tokens.py`): the API
  is the OAuth 2.1 server for the MCP server at `/mcp`. MCP tokens are `typ:
  mcp_access`, audience-bound, scoped (`finance:read`, `finance:rules.write`,
  `finance:planning.write`), and checked against their grant on every use.
  **Routes are web-only by default**: a route the MCP tools need opts in by
  typing its user as `CurrentUserOrMcpRead` / `CurrentUserOrMcpRulesWrite`
  instead of `CurrentUser`. Planning write routes take `PlanningWriter`
  (`core/planning_write.py`): it returns a `Caller` (user + verified
  `grant_id`/`client_id`; record those, never request values) and applies the
  per-user write and dry-run rate limits. `dry_run` must be a JSON body field
  (even on a DELETE): a request without a body counts against the write budget.
  Such routes call `services/planning_writes.run_write` (dry_run in a
  savepoint, DB idempotency, encrypted append-only `audit_entries` row); add a
  target's allow-listed fields to `TARGETS` there. `GET /audit` and
  `POST /audit/{id}/undo` are web-session only (`CurrentUser`) and must stay so.
  Keep that allowlist minimal and never add auth, banking-connection or
  account-management routes. The user's DEK is wrapped under the
  auth code, then under each rotating refresh token (never stored usable).

## Workflow

Branch → PR → squash-merge to `main`. **Pushing to `main` auto-deploys** via
`.github/workflows/deploy.yml` (runs API tests, then `deploy/deploy.sh` over
SSH). Don't run `deploy/deploy.sh` by hand. It refuses a dirty tree (untracked
files included) and dumps the database before a migrating deploy; the deploy
scripts are tested by `./deploy/test-deploy.sh` (no Docker needed, runs in
CI). End commit messages and PR bodies with the standard Claude Code
co-author / attribution lines.
