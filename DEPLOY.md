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

Every merge to `main` runs this from GitHub Actions (`.github/workflows/deploy.yml`),
so a merge is a production deploy. What it does:

1. **Refuses a dirty working tree.** A modified, staged or untracked file stops
   the deploy before anything is sent. It ships only `git archive HEAD`, so
   ignored files (`.env`, `node_modules`) never reach the server either.
2. Syncs that commit to `~/finance-tracker` (`rsync --delete`; `.env.production`
   on the server is kept).
3. On the server, runs `deploy/preflight-sites.sh`, then
   `deploy/pre-migration-dump.sh` (see Rollback), then
   `docker compose up -d --build`, then `deploy/smoke.sh`.

The api container runs `alembic upgrade head` every time it starts, so a
release that contains a migration applies it on deploy.

## Migration policy

- **Schema migrations are additive: expand first, contract later.** Add columns
  and tables (nullable or with a server default) in one release; drop or rename
  only in a later release, after no running code reads the old shape. That way
  the previous release still runs on the new schema, and a code-only rollback
  stays possible.
- **Every migration has a working `downgrade()`.** A data migration that rewrites
  rows first copies the old values into a backup table, and its `downgrade()`
  restores from that table. Test up, down, up on a fixture.
- **Merge a migration on its own.** Don't put two migrations in one deploy, so a
  rollback is one `downgrade` step.

## Rollback

A **pre-migration dump** happens automatically. Before `up`,
`deploy/pre-migration-dump.sh` builds the new api image and runs
`alembic current` with it:
- **at head:** nothing to migrate, so no dump.
- **behind head (or a new database):** the database is dumped to
  `~/backups/predeploy_<timestamp>.sql.gz` first. An empty or cut-short dump
  stops the deploy, and the running stack keeps serving.
- **unreadable revision:** if the new code doesn't know the database's
  revision, the deploy stops before anything restarts. This is what happens
  when a migration is reverted without being downgraded.

Nightly `backup.sh` rotation also clears these dumps after `KEEP_DAYS`.

### Roll back a release with no migration

Revert the PR on GitHub (`gh pr revert <n>` or the "Revert" button) and merge
the revert. The deploy redeploys the previous code.

### Roll back a release that added a migration

A plain revert does **not** work. The database stays at the new revision, which
the old code doesn't have, so `alembic upgrade head` fails with "Can't locate
revision" and the api won't start. (`pre-migration-dump.sh` now stops that
deploy before the restart, but the release still isn't rolled back.) Do it in
this order:

1. Find the revision to go back to: the reverted migration's `down_revision`
   (in its file under `api/migrations/versions/`).
2. **On the server, while the new release is still running**, downgrade with
   the new code (only it has the migration's `downgrade()`):

   ```bash
   cd ~/finance-tracker
   docker compose -f docker-compose.prod.yml --env-file .env.production exec api alembic current
   docker compose -f docker-compose.prod.yml --env-file .env.production exec api alembic downgrade <down_revision>
   docker compose -f docker-compose.prod.yml --env-file .env.production exec api alembic current   # shows <down_revision>
   ```

   The running code may error on the old schema until step 3 lands. Do step 3
   straight away.
3. Merge the revert PR. Its deploy finds the database at the old code's head,
   so no dump is needed and the api boots.
4. Check the deploy run (`gh run list --workflow deploy.yml`) and the app.

If a downgrade can't restore the data (it fails, or the migration was lossy),
ship a forward fix instead, or restore the pre-migration dump:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production stop api
gunzip -c ~/backups/predeploy_<timestamp>.sql.gz | \
  docker compose -f docker-compose.prod.yml --env-file .env.production exec -T db \
  sh -c 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB" && psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

Then deploy the code that matches the dump (the revert). Anything written after
the dump is lost, so this is the last resort.

**Drill (2026-10-10, local Docker, Postgres 16):** release "new" = `main`
(head `c1d2e3f4a5b6`, the OAuth tables), "old" = the commit before it (head
`b0c1d2e3f4a5`). Results:
1. The new code's `upgrade head` applied `c1d2e3f4a5b6`, and `alembic current`
   showed `c1d2e3f4a5b6 (head)`.
2. Naive revert: the old code's `upgrade head` failed with "Can't locate
   revision identified by 'c1d2e3f4a5b6'".
3. `alembic downgrade b0c1d2e3f4a5` with the new code worked, and the old code's
   `alembic current` then showed `b0c1d2e3f4a5 (head)`.
4. The old code booted (`upgrade head` was a no-op, then "Application startup
   complete").

Repeat the drill when the procedure changes.

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

Before every deploy, `deploy/preflight-sites.sh` asks compose which folder it
will mount, so `SITES_DIR` may use anything compose accepts (`${HOME}/x`,
quotes, `export`, comments). It then:
- creates that folder as the deploy user, so Docker doesn't create it owned by
  root;
- refuses a folder inside `~/finance-tracker`;
- refuses any symlink in it, including `SITES_DIR` itself being a symlink;
- validates the Caddyfile with the site files using the real Caddy image.

If any of that fails, the deploy stops and the running Caddy keeps serving. It
needs `python3` on the server, which Ubuntu and Debian include.

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
- **Inline scripts and styles:** prefer moving them into `.js`/`.css` files.
  Next best is allowing each inline block by its hash: add
  `'sha256-<base64 hash>'` to `script-src` or `style-src` (the browser
  console prints the hash it expected). Hashes don't cover `style=""`
  attributes. Only if a page can't be changed, use the documented override:
  the full default policy plus `'unsafe-inline'`. Whatever you change, copy
  the whole policy: an override that leaves out `frame-ancestors`,
  `object-src` or `base-uri` loses them.
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
15 3 * * * $HOME/finance-tracker/deploy/backup.sh >> $HOME/backups/backup.log 2>&1
```

`backup.sh` and the pre-migration dump both use `deploy/pg-dump.sh`. It refuses
a dump that doesn't end with pg_dump's "dump complete" line, so an empty or
cut-short dump fails loudly and leaves no file behind.

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
