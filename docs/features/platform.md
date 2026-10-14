# Platform: health, CI and deploy

## Health

`GET /api/v1/health` (`routers/health.py`) runs `SELECT 1` and returns
`{status: healthy|degraded, database}`, always with HTTP 200.
`deploy/smoke.sh` calls it after every deploy.

## Local and production stack

- `docker-compose.yml` (dev): `db` (Postgres 16, `127.0.0.1:5433`), `api`
  (runs `alembic upgrade head` then uvicorn with reload), `ui` (Vite),
  profile `test` (`test`, `mcp-test`), profile `build` (`ui-build`).
- `docker-compose.prod.yml`: `db`, `api` (2 workers, forwarded-allow-ips
  pinned to Caddy), `mcp`, `caddy` (built from `deploy/ui.Dockerfile`, serves
  the UI, proxies `/api/*`, `/mcp` and the OAuth well-known endpoints, plus
  extra static sites from `docs/extra-sites/`-style folders).
- Settings: `api/app/core/config.py`, `.env.example`,
  `.env.production.example`.

## CI and deploy

- `.github/workflows/test.yml`: on PRs (path filtered) and from deploy (all
  jobs): API tests, MCP tests, Caddy and deploy-script tests, UI tests, types,
  lint, build, production UI image, and the `workflows` job (workflow checks,
  audit gate, **feature-docs check**). `required` is the one status to watch.
- `.github/workflows/deploy.yml`: push to `main` runs `test.yml`, then
  `deploy/deploy.sh` over SSH (dirty-tree refusal, pre-migration dump,
  smoke test).
- `.github/workflows/audit.yml`: weekly npm and pip audits with a dated
  ignore list.
- `.github/scripts/check_feature_docs.py`: keeps `docs/features/` in step
  with the code (see [README.md](README.md)).

## Touchpoints

| # | Answer |
|---|---|
| 1 Tables | none; migrations run at container boot. |
| 2 Purge | n/a. |
| 3 Deletion | n/a. |
| 4 Demo mode | `/health` is `UNSAMPLED_BY_DESIGN`. |
| 5 Ownership | n/a. |
| 6 Scopes | Health is public. |
| 7 Claude tools | none. |
| 8 Audit | n/a. |
| 9 Bank sync | n/a. |
| 10 Home | n/a. |
| 11 UI routes | none. |
| 12 Tests | `deploy/test-caddy.sh`, `deploy/test-deploy.sh`, `.github/scripts/test_*.py`. |
| 13 Docs | `DEPLOY.md`, `CLAUDE.md` "Commands". |
