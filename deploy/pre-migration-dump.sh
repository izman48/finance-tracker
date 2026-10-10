#!/usr/bin/env bash
# Pre-migration safety net. Runs ON THE SERVER from the repo folder; deploy.sh
# calls it after syncing the new code and before `docker compose up`, where
# the api runs `alembic upgrade head` on boot.
#
# Builds the new api image and asks it for the database's revision. If that
# isn't the new code's head, the deploy will migrate, so the database is
# dumped first (into $BACKUP_DIR, default ~/backups) and the deploy stops if
# the dump is empty. If the new code can't read the revision at all (e.g. a
# revert of a migration that wasn't downgraded first), the deploy stops
# before anything is restarted. See DEPLOY.md "Rollback".
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
compose() { docker compose -f docker-compose.prod.yml --env-file .env.production "$@"; }

compose build api
compose up -d --wait db
if ! current="$(compose run --rm --no-deps -T api alembic current)"; then
  echo "pre-migration: the new code can't read the database's migration revision." >&2
  echo "pre-migration: if this deploy reverts a migration, downgrade first (DEPLOY.md, Rollback)." >&2
  exit 1
fi

if grep -q '(head)' <<<"$current"; then
  echo "pre-migration: database already at head, no dump needed"
  exit 0
fi

echo "pre-migration: this deploy runs a migration, dumping the database first"
(umask 077; mkdir -p "$BACKUP_DIR")
./deploy/pg-dump.sh "$BACKUP_DIR/predeploy_$(date +%Y%m%dT%H%M%S).sql.gz"
