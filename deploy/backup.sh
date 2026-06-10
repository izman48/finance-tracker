#!/usr/bin/env bash
# Nightly Postgres backup with rotation. Run from cron on the server:
#   15 3 * * * $HOME/finance-tracker/deploy/backup.sh >> $HOME/backups/backup.log 2>&1
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/finance-tracker}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

cd "$APP_DIR"
set -a; . ./.env.production; set +a

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F)
OUT="$BACKUP_DIR/finance_${STAMP}.sql.gz"

docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT"

# Refuse to count an empty dump as success.
[ -s "$OUT" ] || { echo "$(date -Is) backup EMPTY: $OUT"; exit 1; }
gunzip -t "$OUT"

# Rotate: drop dumps older than KEEP_DAYS.
find "$BACKUP_DIR" -name 'finance_*.sql.gz' -mtime "+$KEEP_DAYS" -delete

echo "$(date -Is) backup OK: $OUT ($(du -h "$OUT" | cut -f1))"
