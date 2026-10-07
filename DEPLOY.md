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

Before every deploy, `deploy/preflight-sites.sh` creates the folder (as the
deploy user, so Docker doesn't create it owned by root), refuses any symlink in
it, and validates the Caddyfile with the site files using the real Caddy image.
If any of that fails, the deploy stops and the running Caddy keeps serving.

`import static_site <name>` serves `<name>/` with automatic HTTPS, HSTS,
`nosniff`, frame denial, a Referrer-Policy and Permissions-Policy, a strict
Content-Security-Policy (same-origin only, plus Google Fonts, no form posts),
gzip/zstd, `no-cache` on pages and a one-day cache on other files that exist,
no directory listings and no dotfiles. It also sends
`X-Robots-Tag: noindex, nofollow`.

A `header` line *after* the import replaces that header's whole value. The
example in `docs/extra-sites/example.caddy` has the exact lines for these
overrides:
- **Allow indexing:** `header X-Robots-Tag "all"`.
- **Inline scripts and styles:** a single-file page with inline `<script>`,
  `<style>` or `style=""` needs the documented CSP override. It is the full
  default policy plus `'unsafe-inline'`. Copy it whole: a CSP override that
  leaves out `frame-ancestors`, `object-src` or `base-uri` loses them.
- **A client's own apex domain:** the default HSTS has `includeSubDomains`.
  On an apex domain (`example.com`, not `site.example.com`) that forces HTTPS
  on every subdomain the client has, including ones not served from here. Use
  `header Strict-Transport-Security "max-age=31536000"` there.

**Site content is trusted, like config.** A site file is full Caddy config, and
Caddy follows symlinks, so a link in a site folder could serve any file in the
container, including the app's TLS keys. Only the server owner may write to
`~/sites`: keep it `chmod 755` and owned by the deploy user. The preflight
refuses symlinks at deploy time, but a reload doesn't run the preflight, so
copy content without them.

To add or update a site:

1. Point the hostname's DNS A record at the server (Caddy needs it to get the
   certificate).
2. Copy the site in without symlinks or dotfiles. From your machine:

   ```bash
   rsync -r --no-links --exclude='.*' mysite.caddy mysite <ssh-host>:sites/
   ```

3. On the server, from `~/finance-tracker`, validate. **If it fails, delete
   the file you just added before doing anything else.** A broken file left in
   the folder fails the next deploy. If the container restarts on its own (a
   reboot), Caddy won't start and the app goes down.

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec caddy caddy validate --config /etc/caddy/Caddyfile
   ```

4. Reload with no downtime. A rejected reload leaves the running config
   serving:

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```

Content-only changes (files under `mysite/`) are live immediately; no reload.
`./deploy/test-caddy.sh` (run in CI) checks the Caddyfile against the real Caddy
image, with and without the example site, and checks the preflight.

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
