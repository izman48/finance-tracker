#!/usr/bin/env bash
# pg-dump.sh <out.sql.gz> — dump the production database to a gzip file.
# Runs ON THE SERVER. Used by the nightly backup (backup.sh) and before a
# deploy that migrates (pre-migration-dump.sh), so both refuse the same bad
# dumps: a failed pg_dump, or output that doesn't end with pg_dump's
# "dump complete" trailer (empty or cut short). On failure no file is left.
set -euo pipefail
# Dumps hold emails, password hashes and wrapped keys: owner-only files.
umask 077

OUT="${1:?usage: pg-dump.sh <out.sql.gz>}"
cd "$(dirname "$0")/.."
set -a; . ./.env.production; set +a

PARTIAL="$OUT.partial"
trap 'rm -f "$PARTIAL"' EXIT
docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$PARTIAL"

if ! gunzip -c "$PARTIAL" | tail -n 5 | grep -q "PostgreSQL database dump complete"; then
  echo "$(date -Is) dump EMPTY or incomplete, not kept: $OUT" >&2
  exit 1
fi
mv "$PARTIAL" "$OUT"
echo "$(date -Is) dump OK: $OUT ($(du -h "$OUT" | cut -f1))"
