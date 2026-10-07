# Production deployment (any Docker-capable VPS)

Architecture: Caddy (HTTPS, serves the built React app, proxies `/api/*`) → FastAPI → Postgres.
All in Docker via `docker-compose.prod.yml`; UI and API share one origin so no CORS is involved.

## One-time server setup

1. **Install Docker** (needs sudo, run interactively on the server):

   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER   # then log out/in
   ```

2. **DNS**: point an A record for your chosen domain (e.g. `finance.yourdomain.com`)
   at the server IP. Caddy obtains/renews Let's Encrypt certificates automatically.

3. **Secrets**: on the server, in `~/finance-tracker`:

   ```bash
   cp .env.production.example .env.production
   # fill in DOMAIN, POSTGRES_PASSWORD, SECRET_KEY, ENCRYPTION_KEY, TrueLayer credentials
   chmod 600 .env.production
   ```

4. **TrueLayer console** (https://console.truelayer.com/): add
   `https://<DOMAIN>/api/v1/banking/callback` as a redirect URI.

5. **Firewall**: allow only 22, 80, 443 (Hetzner Cloud Firewall or `ufw`).

## Deploying (initial and every update)

From your machine:

```bash
./deploy/deploy.sh <ssh-host>   # rsyncs the repo and runs docker compose up -d --build
```

`<ssh-host>` is an `~/.ssh/config` alias or `user@ip`; you can set `DEPLOY_HOST`
in your environment instead of passing it each time.

## Extra static sites (optional)

Caddy owns ports 80/443, so it can also serve small static sites on their own
hostnames next to the app. Each site is two things in a host folder that is
mounted read-only into the Caddy container at `/sites`:

```
~/sites/
  mysite.caddy     # the site block: its hostname and `import static_site mysite`
  mysite/          # the site's files (index.html, css, images, ...)
```

The folder is `~/sites` by default; set `SITES_DIR` in `.env.production` to use
another path. **Keep it outside `~/finance-tracker`**: every deploy runs
`rsync --delete` into that folder and removes anything that isn't in git. With
the folder empty or missing, the app is served exactly as without it.

`import static_site <name>` serves `<name>/` with automatic HTTPS, HSTS,
`nosniff`, frame denial, a Referrer-Policy and Permissions-Policy, a strict
Content-Security-Policy (same-origin only, plus Google Fonts), gzip/zstd,
`no-cache` on pages and a one-day cache on other files, no directory listings
and no dotfiles. It also sends `X-Robots-Tag: noindex, nofollow`; to let search
engines index the site, override it *after* the import. A site that needs more
(e.g. an embedded player) can override `Content-Security-Policy` the same way.
Example (also in `docs/extra-sites/`):

```caddy
example.com {
	import static_site example
	# header X-Robots-Tag "all"
}
```

To add or update a site, on the server:

1. Point the hostname's DNS A record at the server (Caddy needs it to get the
   certificate).
2. `mkdir -p ~/sites` the first time (otherwise Docker creates it owned by
   root), then copy in `mysite.caddy` and the `mysite/` folder. Only the server
   owner should be able to write here: a site file is full Caddy config.
3. Check, then reload with no downtime (from `~/finance-tracker`). A first-time
   folder only appears in the container after the next deploy or
   `docker compose ... up -d caddy`:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec caddy caddy validate --config /etc/caddy/Caddyfile
   docker compose -f docker-compose.prod.yml --env-file .env.production exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```

   A rejected reload leaves the running config serving. But a broken site file
   left in the folder stops Caddy from starting on the next deploy, taking the
   app down with it, so remove it if validation fails.

Content-only changes (files under `mysite/`) are live immediately; no reload.
`./deploy/test-caddy.sh` (run in CI) checks the Caddyfile against the real Caddy
image, with and without the example site.

## Moving to a new server

Nothing in this repo is tied to a specific machine — the domain, secrets, and
TrueLayer credentials all live in `.env.production` on the server. To migrate:

1. Dump the database (see Backups) and copy the dump plus `.env.production`
   to the new server — these are the only two stateful things.
2. Do the one-time setup above on the new machine, deploy, then restore the
   dump with `psql` into the fresh `db` container.
3. Point the DNS A record at the new IP. Caddy obtains a fresh certificate
   automatically; TrueLayer needs no changes as long as the domain stays the same.

## Backups

Bank data lives in the `postgres_data` volume. Nightly dump (server crontab, `crontab -e`):

```cron
15 3 * * * cd $HOME/finance-tracker && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db pg_dump -U finance_user finance_db | gzip > $HOME/backups/finance_$(date +\%F).sql.gz
```

Create `~/backups` first; copy dumps off the server periodically (they contain
financial data — treat them as sensitive).

## Useful commands (on the server, in ~/finance-tracker)

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps       # status
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api
docker compose -f docker-compose.prod.yml --env-file .env.production restart api
```

## Going live with real bank data later

Set `TRUELAYER_SANDBOX=false` in `.env.production` (requires TrueLayer production
access for your app) and redeploy. The API refuses to boot in live mode with a
weak `SECRET_KEY`.
