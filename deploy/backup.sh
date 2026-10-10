#!/usr/bin/env bash
# Nightly Postgres backup with rotation. Run from cron on the server:
#   15 3 * * * $HOME/finance-tracker/deploy/backup.sh >> $HOME/backups/backup.log 2>&1
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/finance-tracker}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

cd "$APP_DIR"
mkdir -p "$BACKUP_DIR"

# Refuses an empty or cut-short dump and leaves no file behind.
./deploy/pg-dump.sh "$BACKUP_DIR/finance_$(date +%F).sql.gz"

# Rotate: drop dumps older than KEEP_DAYS (nightly and pre-migration ones).
find "$BACKUP_DIR" \( -name 'finance_*.sql.gz' -o -name 'predeploy_*.sql.gz' \) -mtime "+$KEEP_DAYS" -delete
