#!/usr/bin/env bash
# Tests for scripts/dev-env.sh, with uv and docker replaced by stubs that keep
# their state in files. Needs only bash and git (no Docker, no Python).
#   - one shared venv per requirements hash: built once, reused by every
#     worktree, rebuilt once when api/requirements.txt changes
#   - one shared Postgres bound to 127.0.0.1 only, with a local-only password
#     kept out of the repo, and one database per worktree, dropped on `drop`
#   - no personal paths: the shared location is $NILU_DEV_HOME, else a
#     generic default under the user's cache directory
# Usage: ./scripts/test-dev-env.sh
# Checks are single-quoted strings run by `check` (eval), so their variables
# expand there, not where they are set.
# shellcheck disable=SC2016,SC2034
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/dev-env.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

failures=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1" >&2; failures=$((failures + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }

# --- stubs ---------------------------------------------------------------------
STUBS="$TMP/stubs"
mkdir -p "$STUBS"
export CALLS="$TMP/calls.log" STATE="$TMP/docker-state"
mkdir -p "$STATE/dbs"

cat > "$STUBS/uv" <<'STUB'
#!/usr/bin/env bash
echo "uv $*" >> "$CALLS"
[ "$1 $2" = "pip install" ] && [ "${FAKE_UV_FAIL:-0}" = 1 ] && { echo "network error" >&2; exit 2; }
if [ "$1" = venv ]; then
  dir="${@: -1}"
  mkdir -p "$dir/bin" && printf '#!/bin/sh\n' > "$dir/bin/python" && chmod +x "$dir/bin/python"
fi
exit 0
STUB
# tr stub: fails with no output when FAKE_TR_FAIL=1 (a failed password write).
cat > "$STUBS/tr" <<'STUB'
#!/usr/bin/env bash
[ "${FAKE_TR_FAIL:-0}" = 1 ] && exit 1
exec /usr/bin/tr "$@"
STUB
cat > "$STUBS/docker" <<'STUB'
#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
case "$1" in
  inspect) [ -f "$STATE/container" ] || { echo; exit 1; }; cat "$STATE/container" ;;  # real docker prints a blank line when missing
  run) echo true > "$STATE/container"
       # another setup created it first: the name is taken
       [ "${FAKE_RUN_CONFLICT:-0}" = 1 ] && { echo "Conflict. The container name is already in use" >&2; exit 125; } ;;
  start) echo true > "$STATE/container" ;;
  port) echo "${FAKE_PORT_BIND:-127.0.0.1:55436}" ;;
  exec)
    case " $* " in
      *" pg_isready "*) exit 0 ;;
      *" psql "*) db="$(printf '%s' "$*" | sed -n "s/.*datname='\([^']*\)'.*/\1/p")"
                  [ -f "$STATE/dbs/$db" ] && echo 1 ;;
      *" createdb "*) touch "$STATE/dbs/${@: -1}" ;;
      *" dropdb "*) rm -f "$STATE/dbs/${@: -1}" ;;
    esac ;;
esac
exit 0
STUB
chmod +x "$STUBS"/*
export PATH="$STUBS:$PATH"
export NILU_DEV_HOME="$TMP/shared"

# worktree <dir> — a minimal checkout with the script and a requirements file.
worktree() {
  local dir="$1"
  mkdir -p "$dir/api" "$dir/scripts"
  cp "$SCRIPT" "$dir/scripts/dev-env.sh"
  [ -f "$dir/api/requirements.txt" ] || echo "fastapi==0.136.3" > "$dir/api/requirements.txt"
}
run() { (cd "$1" && bash scripts/dev-env.sh "${@:2}") > "$TMP/out.log" 2>&1; }
count() { grep -c -- "$1" "$CALLS" 2>/dev/null || true; }

# --- shared venv ------------------------------------------------------------------
A="$TMP/wt/eng-a-T-1"; B="$TMP/wt/eng-b-T-2"
worktree "$A"; worktree "$B"

run "$A" setup
check "first setup builds the shared venv once" '[ "$(count "uv venv")" = 1 ] && [ "$(count "uv pip install")" = 1 ]'
check "the venv is Python 3.12" 'grep -q -- "uv venv.*--python 3.12" "$CALLS"'
check "the worktree's api/.venv links to the shared venv" \
  '[ -L "$A/api/.venv" ] && [[ "$(readlink "$A/api/.venv")" == "$NILU_DEV_HOME/venvs/"* ]]'

run "$B" setup
check "a second worktree reuses it (no new build)" '[ "$(count "uv venv")" = 1 ]'
check "both worktrees link the same venv" '[ "$(readlink "$A/api/.venv")" = "$(readlink "$B/api/.venv")" ]'

echo "google-re2==1.1.20250805" >> "$B/api/requirements.txt"
run "$B" setup
check "changed requirements rebuild once" '[ "$(count "uv venv")" = 2 ]'
check "the new venv is a different directory" '[ "$(readlink "$A/api/.venv")" != "$(readlink "$B/api/.venv")" ]'
run "$B" setup
check "and the next run reuses the new one" '[ "$(count "uv venv")" = 2 ]'

F="$TMP/wt/failing-build"; worktree "$F"; echo "pydantic==2.9.2" >> "$F/api/requirements.txt"
if FAKE_UV_FAIL=1 run "$F" setup; then fail "a failed venv build fails setup"; else pass "a failed venv build fails setup"; fi
check "a failed build is never marked ready or linked" \
  '! ls "$NILU_DEV_HOME"/venvs/*/.ready 2>/dev/null | xargs -n1 dirname | grep -qv -e "^$(dirname "$(readlink "$A/api/.venv")")" && [ ! -e "$F/api/.venv" ] && [ "$(ls "$NILU_DEV_HOME"/venvs/*/.ready | wc -l | tr -d " ")" = 2 ]'
check "and the lock is released" '! ls -d "$NILU_DEV_HOME"/venvs/*.lock 2>/dev/null'
builds="$(count "uv venv")"; run "$F" setup
check "the next run builds it again and succeeds" '[ "$(count "uv venv")" = $((builds + 1)) ] && [ -L "$F/api/.venv" ]'

mkdir -p "$TMP/wt/own-venv/api/.venv"; worktree "$TMP/wt/own-venv"
if run "$TMP/wt/own-venv" setup; then fail "a real api/.venv directory is refused"; else
  check "a real api/.venv directory is refused, not deleted" '[ -d "$TMP/wt/own-venv/api/.venv" ] && [ ! -L "$TMP/wt/own-venv/api/.venv" ]'
fi

# --- shared Postgres -------------------------------------------------------------
check "one Postgres container is created, once" '[ "$(count "docker run")" = 1 ]'
check "it binds to 127.0.0.1 only" 'grep "docker run" "$CALLS" | grep -q -- "-p 127.0.0.1:55436:5432" && ! grep "docker run" "$CALLS" | grep -q -- "-p 0.0.0.0"'
check "the password goes in by env file, never on the command line" \
  'grep "docker run" "$CALLS" | grep -q -- "--env-file" && ! grep -q "POSTGRES_PASSWORD" "$CALLS"'
pwfile="$NILU_DEV_HOME/postgres.env"
check "the password file is private to the user" '[ "$(stat -f %Lp "$pwfile" 2>/dev/null || stat -c %a "$pwfile")" = 600 ]'
check "the password is generated, not a fixed value in the script" \
  'pw="$(sed -n "s/^POSTGRES_PASSWORD=//p" "$pwfile")"; [ ${#pw} -ge 24 ] && ! grep -q "$pw" "$SCRIPT"'

echo false > "$STATE/container"
run "$A" setup
check "a stopped container is started, not recreated" '[ "$(count "docker start")" = 1 ] && [ "$(count "docker run")" = 1 ]'

if FAKE_PORT_BIND="0.0.0.0:55436" run "$A" setup; then fail "a container published beyond 127.0.0.1 is refused"; else
  pass "a container published beyond 127.0.0.1 is refused"
fi

rm -f "$STATE/container" "$A/.env.dev-db"
FAKE_RUN_CONFLICT=1 run "$A" setup
check "a setup that loses the race to create the container carries on" '[ -f "$A/.env.dev-db" ]'

# --- one database per worktree ----------------------------------------------------
dbs() { ls "$STATE/dbs"; }
check "each worktree gets its own database (A, B and the rebuilt one; the refused one got none)" '[ "$(dbs | wc -l | tr -d " ")" = 3 ]'
db_a="$(sed -n 's#^DATABASE_URL=.*/##p' "$A/.env.dev-db")"
db_b="$(sed -n 's#^DATABASE_URL=.*/##p' "$B/.env.dev-db")"
check "named from the worktree, and different" '[[ "$db_a" == wt_eng_a_t_1_* ]] && [[ "$db_b" == wt_eng_b_t_2_* ]]'
check "DATABASE_URL points at 127.0.0.1 and the shared port" 'grep -q "^DATABASE_URL=postgresql://[^@]*@127.0.0.1:55436/$db_a$" "$A/.env.dev-db"'
check "the env file is git-ignored (.env*)" 'git -C "$REPO_ROOT" check-ignore -q .env.dev-db'
check "the api/.venv link is git-ignored (a symlink, not a directory)" 'git -C "$REPO_ROOT" check-ignore -q --no-index api/.venv'
before="$(count createdb)"; run "$A" setup
check "re-running doesn't create the database again" '[ "$(count createdb)" = "$before" ]'

W="$TMP/wt/Weird Name.With-Dots"; worktree "$W"; run "$W" setup
db_w="$(sed -n 's#^DATABASE_URL=.*/##p' "$W/.env.dev-db")"
check "odd directory names become a safe identifier" '[[ "$db_w" =~ ^wt_weird_name_with_dots_[0-9a-f]{8}$ ]]'
L="$TMP/wt/$(printf 'x%.0s' {1..90})"; worktree "$L"; run "$L" setup
db_l="$(sed -n 's#^DATABASE_URL=.*/##p' "$L/.env.dev-db")"
check "and stay within Postgres's 63 characters" '[ ${#db_l} -le 63 ]'

# --- drop -----------------------------------------------------------------------
run "$A" drop
check "drop removes the worktree's database only" '[ ! -f "$STATE/dbs/$db_a" ] && [ -f "$STATE/dbs/$db_b" ]'
check "drop removes the env file and the venv link, not the shared venv" \
  '[ ! -e "$A/.env.dev-db" ] && [ ! -L "$A/api/.venv" ] && [ -d "$(readlink "$B/api/.venv")" ]'
rm -rf "$B"
(cd "$W" && bash scripts/dev-env.sh drop "$B/") > "$TMP/out.log" 2>&1
check "drop <path> works after the worktree is gone, trailing slash or not" '[ ! -f "$STATE/dbs/$db_b" ] && grep -q "dropped" "$TMP/out.log"'
(cd "$W" && bash scripts/dev-env.sh drop "$B") > "$TMP/out.log" 2>&1
check "a path with no database says so, not \"dropped\"" 'grep -q "no database for" "$TMP/out.log" && ! grep -q "dropped" "$TMP/out.log"'
if (cd "$W" && bash scripts/dev-env.sh drop "wt/relative") > "$TMP/out.log" 2>&1; then fail "a relative path is refused"; else
  pass "a relative path is refused"
fi

# --- no personal paths ---------------------------------------------------------
check "the script names no user's home directory" '! grep -nE "/(Users|home)/" "$SCRIPT"'
out="$(unset NILU_DEV_HOME XDG_CACHE_HOME; HOME="$TMP/home" bash "$SCRIPT" home)"
check "the default location is generic (\$HOME/.cache/nilu-dev)" '[ "$out" = "$TMP/home/.cache/nilu-dev" ]'

# --- a failed password write -----------------------------------------------------
P="$TMP/wt/pw-fails"; worktree "$P"
export NILU_DEV_HOME="$TMP/shared-pw"
if FAKE_TR_FAIL=1 run "$P" setup; then fail "a failed password write fails setup"; else
  pass "a failed password write fails setup"
fi
check "and leaves no password file for later runs to trust" '[ ! -e "$NILU_DEV_HOME/postgres.env" ] && ! ls "$NILU_DEV_HOME"/postgres.env.* 2>/dev/null'
run "$P" setup
check "the next run writes a full one" 'pw="$(sed -n "s/^POSTGRES_PASSWORD=//p" "$NILU_DEV_HOME/postgres.env")"; [ ${#pw} -ge 24 ]'

if [ "$failures" -gt 0 ]; then echo "$failures failed" >&2; exit 1; fi
echo "all passed"
