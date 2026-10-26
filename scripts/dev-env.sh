#!/usr/bin/env bash
# A warm local environment for a checkout or git worktree, shared across them:
#   - one Python 3.12 venv per hash of api/requirements.txt, built once and
#     linked as api/.venv in every worktree (rebuilt once when it changes)
#   - one long-running Postgres on 127.0.0.1 only, with one database per
#     worktree, for migration checks and the dev API (the test suite itself
#     runs on in-memory SQLite and needs neither)
#
# Usage (from the checkout):
#   scripts/dev-env.sh [setup]    link the venv, start Postgres, create this
#                                 worktree's database, write .env.dev-db
#   scripts/dev-env.sh drop [dir] drop the database of this worktree (or of
#                                 <dir>, even after it was removed)
#   scripts/dev-env.sh home       print the shared location
# Then: api/.venv/bin/pytest tests -n auto        (from api/)
#       set -a; . ./.env.dev-db; set +a            (DATABASE_URL for alembic / uvicorn)
#
# Settings (environment):
#   NILU_DEV_HOME          shared location (default: $XDG_CACHE_HOME/nilu-dev,
#                          else ~/.cache/nilu-dev)
#   NILU_DEV_PG_PORT       host port, bound to 127.0.0.1 (default 55436)
#   NILU_DEV_PG_CONTAINER  container name (default nilu-dev-postgres)
# Local development only: production and CI never run this. Tests:
# scripts/test-dev-env.sh.
set -euo pipefail

SHARED="${NILU_DEV_HOME:-${XDG_CACHE_HOME:-$HOME/.cache}/nilu-dev}"
PG_PORT="${NILU_DEV_PG_PORT:-55436}"
PG_CONTAINER="${NILU_DEV_PG_CONTAINER:-nilu-dev-postgres}"
PG_IMAGE="postgres:16-alpine"
PG_USER="nilu_dev"
PG_ENV="$SHARED/postgres.env"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

die() { echo "dev-env: $*" >&2; exit 1; }
sha() { if command -v sha256sum >/dev/null; then sha256sum; else shasum -a 256; fi | cut -c1-"$1"; }

# --- venv ----------------------------------------------------------------------

# The venv for this checkout's requirements: built under a lock (several
# agents may set up at once) and marked ready only when complete. It runs in
# $(...), where `set -e` is off (bash 3.2 has no inherit_errexit) and an
# EXIT trap doesn't fire, so every step that can fail releases the lock,
# removes the partial venv and exits explicitly.
shared_venv() {
  local key dir lock waited=0
  key="$( { echo "python3.12"; cat "$ROOT/api/requirements.txt"; } | sha 16)"
  dir="$SHARED/venvs/$key"
  lock="$dir.lock"
  mkdir -p "$SHARED/venvs"
  until mkdir "$lock" 2>/dev/null; do
    [ -f "$dir/.ready" ] && { echo "$dir"; return; }
    [ "$waited" -ge 600 ] && die "waited 10 min for $lock; remove it if no setup is running"
    sleep 1; waited=$((waited + 1))
  done
  if [ ! -f "$dir/.ready" ]; then
    echo "dev-env: building the shared venv (requirements changed or first run)" >&2
    rm -rf "$dir"
    uv venv --quiet --python 3.12 "$dir" >&2 || abandon_build "$dir" "$lock"
    uv pip install --quiet --python "$dir/bin/python" -r "$ROOT/api/requirements.txt" >&2 \
      || abandon_build "$dir" "$lock"
    touch "$dir/.ready" || abandon_build "$dir" "$lock"
  fi
  rmdir "$lock"
  echo "$dir"
}

abandon_build() {
  rm -rf "$1"
  rmdir "$2"
  exit 1
}

link_venv() {
  local target="$1" link="$ROOT/api/.venv"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    die "api/.venv is a real directory; move it away to use the shared venv"
  fi
  ln -sfn "$target" "$link"
}

# --- Postgres --------------------------------------------------------------------

# A local-only password, generated once and kept outside the repo. Written
# to a temporary file and moved into place only when complete, so a failed
# write leaves nothing a later run would trust. Runs in $(...): explicit exits.
pg_env() {
  if [ ! -f "$PG_ENV" ]; then
    local password tmp="$PG_ENV.$$"
    password="$(LC_ALL=C tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 32)"
    if [ "${#password}" -ne 32 ]; then rm -f "$tmp"; exit 1; fi
    if ! (umask 077 && printf 'POSTGRES_USER=%s\nPOSTGRES_PASSWORD=%s\n' "$PG_USER" "$password" > "$tmp" \
          && mv "$tmp" "$PG_ENV"); then
      rm -f "$tmp"; exit 1
    fi
  fi
  sed -n 's/^POSTGRES_PASSWORD=//p' "$PG_ENV"
}

start_postgres() {
  local running
  running="$(docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null)" || running=missing
  case "$running" in
    missing)
      # Two first-time setups may race to create it: if the name is taken
      # by the time ours fails, the other one won, and the checks below
      # still apply to it.
      docker run -d --name "$PG_CONTAINER" --restart unless-stopped --env-file "$PG_ENV" \
        -p "127.0.0.1:$PG_PORT:5432" -v nilu-dev-postgres-data:/var/lib/postgresql/data \
        "$PG_IMAGE" >/dev/null \
        || docker inspect "$PG_CONTAINER" >/dev/null 2>&1 \
        || die "could not start $PG_CONTAINER" ;;
    false) docker start "$PG_CONTAINER" >/dev/null ;;
  esac
  # Never reuse a container someone published beyond loopback.
  local bound
  bound="$(docker port "$PG_CONTAINER" 5432)"
  if [ -z "$bound" ] || printf '%s\n' "$bound" | grep -qv '^127\.0\.0\.1:'; then
    die "$PG_CONTAINER is published on '$bound', not only 127.0.0.1; remove it and re-run"
  fi
  local tries=0
  until docker exec "$PG_CONTAINER" pg_isready -q -U "$PG_USER" -d postgres; do
    [ "$tries" -ge 60 ] && die "Postgres did not become ready"
    sleep 0.5; tries=$((tries + 1))
  done
}

# wt_<directory name>_<hash of its path>: a safe identifier, unique per
# worktree path, within Postgres's 63 characters.
db_name() {
  local path="$1" base
  base="$(basename "$path" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '_' | sed 's/__*/_/g; s/^_//; s/_$//' | cut -c1-40)"
  echo "wt_${base}_$(printf '%s' "$path" | sha 8)"
}

create_db() {
  local db="$1"
  if [ "$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'")" != 1 ]; then
    docker exec "$PG_CONTAINER" createdb -U "$PG_USER" "$db"
  fi
}

# --- commands --------------------------------------------------------------------

setup() {
  local started=$SECONDS venv password db
  mkdir -p "$SHARED"
  venv="$(shared_venv)" || die "building the shared venv failed; nothing was linked"
  link_venv "$venv"
  password="$(pg_env)" || die "could not write $PG_ENV"
  start_postgres
  db="$(db_name "$ROOT")"
  create_db "$db"
  (umask 077 && echo "DATABASE_URL=postgresql://$PG_USER:$password@127.0.0.1:$PG_PORT/$db" > "$ROOT/.env.dev-db")
  echo "dev-env: ready in $((SECONDS - started))s"
  echo "  venv:     api/.venv -> $venv"
  echo "  database: $db on 127.0.0.1:$PG_PORT (DATABASE_URL in .env.dev-db)"
}

# The database is named from the worktree's absolute path as setup saw it,
# so <dir> must be that path (a trailing slash is ignored).
drop() {
  local path="${1:-$ROOT}" db
  while [ "${path%/}" != "$path" ] && [ "$path" != / ]; do path="${path%/}"; done
  case "$path" in /*) ;; *) die "drop needs the worktree's absolute path" ;; esac
  db="$(db_name "$path")"
  if [ "$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$db'")" = 1 ]; then
    docker exec "$PG_CONTAINER" dropdb -U "$PG_USER" "$db"
    echo "dev-env: dropped $db"
  else
    echo "dev-env: no database for $path ($db)"
  fi
  if [ "$path" = "$ROOT" ]; then
    rm -f "$ROOT/.env.dev-db"
    if [ -L "$ROOT/api/.venv" ]; then rm "$ROOT/api/.venv"; fi
  fi
}

case "${1:-setup}" in
  setup) setup ;;
  drop) drop "${2:-}" ;;
  home) echo "$SHARED" ;;
  *) die "usage: scripts/dev-env.sh [setup | drop [dir] | home]" ;;
esac
