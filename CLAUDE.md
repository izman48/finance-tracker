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
ui/src/
  pages/        the three tabs — DashboardPage (Home), SpendingPage,
                NetWorthPage (Wealth = the balance sheet) — plus
                CommitmentsPage (sub-page off Home), RulesPage (user menu),
                auth pages
  components/   (components/ui = shared primitives incl. Toast/ConfirmDialog
                providers)  lib/ (format, cadence, assets)  types.ts
                services/api.ts  hooks/
  scripts/visual-check.mjs   browser screenshot harness (BASE_URL overridable)
```

The IA is three tabs (Home / Spending / Wealth); `REDESIGN_PLAN.md` records
the redesign and the still-open extensions (demo mode, nudges, theming).

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

**Frontend**:
```bash
cd ui
npm run build    # tsc && vite build — run before merging
npm run lint     # eslint, --max-warnings 0
```

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
- **Decimal-as-string**: money fields arrive from the API as strings. Coerce with
  `Number(...)` before arithmetic in the UI.
- **Mobile grid overflow**: a bare `grid md:grid-cols-2` gives mobile an *implicit
  auto* track that sizes to max-content and overflows (truncate can't shrink it).
  Always set an explicit base column — `grid grid-cols-1 md:grid-cols-2` — so the
  track is `minmax(0,1fr)`. For truncating flex children, add `min-w-0` to the
  growing item and `shrink-0` to siblings that must keep their width.

## Conventions

- **Design system**: dark "ink + mint" theme. Reusable classes live in
  `ui/src/index.css` (`.card`, `.card-pad`, `.btn-primary`, `.btn-ghost`,
  `.input`, `.label`, `.chip-*`, `.seg`/`.seg-active`, `.modal-backdrop`/
  `.modal-panel`, `.banner-ok`/`.banner-err`, `.stat-figure`, `.tnum`). Use them
  rather than re-styling. Colors: `accent` (mint) positive, `neg` (rose), `warn`
  (amber for credit), `pos` (green income). Fonts: Inter (body), Space Grotesk
  (`font-display`). Charts use Recharts; motion uses GSAP and must respect
  `prefers-reduced-motion`.
- **Navigation**: three tabs (Home / Spending / Wealth) — desktop top-nav at
  `lg+`; below `lg` (phones *and* iPad portrait) a bottom tab bar. Keep that
  breakpoint consistent. Rules and account management live in the user menu;
  commitments management is a sub-page off Home.
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

## Workflow

Branch → PR → squash-merge to `main`. **Pushing to `main` auto-deploys** via
`.github/workflows/deploy.yml` (runs API tests, then `deploy/deploy.sh` over
SSH). Don't run `deploy/deploy.sh` by hand. End commit messages and PR bodies
with the standard Claude Code co-author / attribution lines.
