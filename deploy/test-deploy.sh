#!/usr/bin/env bash
# Tests for the deploy scripts, with ssh, rsync and docker replaced by stubs
# that record their calls. Needs only git and bash (no Docker, no server).
#   - deploy.sh refuses a dirty tree (modified, staged or untracked) before
#     anything leaves the machine, and ships exactly the committed files.
#   - pre-migration-dump.sh dumps the database only when the new code has a
#     migration the database hasn't run, and fails the deploy on an empty dump
#     or when it can't tell.
# Usage: ./deploy/test-deploy.sh   (CI runs it in test.yml)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

failures=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1" >&2; failures=$((failures + 1)); }

# --- stubs ---------------------------------------------------------------------
STUBS="$TMP/stubs"
mkdir -p "$STUBS"
export CALLS="$TMP/calls.log" SHIPPED="$TMP/shipped.txt"

cat > "$STUBS/rsync" <<'EOF'
#!/usr/bin/env bash
echo "rsync $*" >> "$CALLS"
src="${@: -2:1}"
(cd "$src" && find . -type f | sort) > "$SHIPPED"
EOF
cat > "$STUBS/ssh" <<'EOF'
#!/usr/bin/env bash
echo "ssh $*" >> "$CALLS"
EOF
# docker compose stub: `run ... alembic current` prints $FAKE_CURRENT (or fails
# when FAKE_CURRENT_FAIL=1); `exec ... pg_dump` prints $FAKE_DUMP.
cat > "$STUBS/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
case " $* " in
  *" alembic current "*)
    [ "${FAKE_CURRENT_FAIL:-0}" = 1 ] && { echo "Can't locate revision" >&2; exit 1; }
    printf '%s\n' "${FAKE_CURRENT:-}" ;;
  *" pg_dump "*) printf '%s' "${FAKE_DUMP:-}" ;;
esac
exit 0
EOF
chmod +x "$STUBS"/*
export PATH="$STUBS:$PATH"

# --- deploy.sh -----------------------------------------------------------------

# fresh_repo — a committed copy of the deploy scripts in its own git repo.
fresh_repo() {
  local dir="$TMP/repo-$RANDOM$RANDOM"
  mkdir -p "$dir"
  cp -R "$REPO_ROOT/deploy" "$dir/deploy"
  cp "$REPO_ROOT/.gitignore" "$dir/.gitignore"
  echo "app" > "$dir/app.txt"
  git -C "$dir" init -q
  git -C "$dir" add -A
  git -C "$dir" -c user.email=t@t -c user.name=t commit -qm init
  echo "$dir"
}

# deploys <repo> — runs deploy.sh against a fake host; output in $TMP/out.
deploys() {
  : > "$CALLS"; rm -f "$SHIPPED"
  "$1/deploy/deploy.sh" deploy-test-host > "$TMP/out" 2>&1
}

repo="$(fresh_repo)"
echo "stray" > "$repo/untracked.txt"
if deploys "$repo"; then fail "deploy with an untracked file succeeded"; else pass "untracked file: deploy exits non-zero"; fi
[ -s "$CALLS" ] && fail "untracked file: rsync/ssh still ran" || pass "untracked file: nothing synced"
grep -q "deploy-test-host" "$TMP/out" && fail "refusal message printed the host" || pass "refusal message does not print the host"

repo="$(fresh_repo)"
echo "changed" >> "$repo/app.txt"
if deploys "$repo"; then fail "deploy with a modified file succeeded"; else pass "modified file: deploy exits non-zero"; fi
[ -s "$CALLS" ] && fail "modified file: rsync/ssh still ran" || pass "modified file: nothing synced"

repo="$(fresh_repo)"
echo "new" > "$repo/staged.txt" && git -C "$repo" add staged.txt
if deploys "$repo"; then fail "deploy with a staged file succeeded"; else pass "staged file: deploy exits non-zero"; fi

repo="$(fresh_repo)"
mkdir -p "$repo/ui/node_modules/pkg" && echo "ignored" > "$repo/ui/node_modules/pkg/index.js"
echo "SECRET=x" > "$repo/.env"
if deploys "$repo"; then pass "clean tree (ignored files only): deploy succeeds"; else fail "clean tree deploy failed: $(cat "$TMP/out")"; fi
expected="$(cd "$repo" && git ls-files | sed 's|^|./|' | sort)"
[ "$(cat "$SHIPPED")" = "$expected" ] \
  && pass "clean tree: ships exactly the committed files" \
  || fail "clean tree: shipped files differ from git ls-files: $(diff <(echo "$expected") "$SHIPPED" || true)"
remote_cmd="$(grep '^ssh ' "$CALLS" || true)"
dump_at="$(grep -bo 'pre-migration-dump.sh' <<<"$remote_cmd" | head -1 | cut -d: -f1)"
up_at="$(grep -bo 'up -d --build' <<<"$remote_cmd" | head -1 | cut -d: -f1)"
[ -n "$dump_at" ] && [ -n "$up_at" ] && [ "$dump_at" -lt "$up_at" ] \
  && pass "server runs the pre-migration dump before up -d" \
  || fail "pre-migration dump not run before up -d: $remote_cmd"

# --- pre-migration-dump.sh -----------------------------------------------------

server="$(fresh_repo)"
echo "POSTGRES_USER=u" > "$server/.env.production"
echo "POSTGRES_DB=d" >> "$server/.env.production"
export BACKUP_DIR="$TMP/backups"
DUMP_OK=$'-- PostgreSQL database dump\nCREATE TABLE t ();\n-- PostgreSQL database dump complete\n'

# dumps <FAKE_CURRENT> <FAKE_DUMP> — runs the server-side script.
dumps() {
  : > "$CALLS"; rm -rf "$BACKUP_DIR"
  FAKE_CURRENT="$1" FAKE_DUMP="$2" "$server/deploy/pre-migration-dump.sh" > "$TMP/out" 2>&1
}
dump_files() { find "$BACKUP_DIR" -type f 2>/dev/null | wc -l | tr -d ' '; }

if dumps "abc123 (head)" "$DUMP_OK"; then pass "at head: exits 0"; else fail "at head failed: $(cat "$TMP/out")"; fi
[ "$(dump_files)" = 0 ] && pass "at head: no dump taken" || fail "at head: a dump was taken"
grep -q 'up -d --no-recreate --wait db' "$CALLS" \
  && pass "starts the db without recreating it" || fail "db start may recreate Postgres: $(grep ' up ' "$CALLS")"

if dumps "abc122" "$DUMP_OK"; then pass "pending migration: exits 0"; else fail "pending migration failed: $(cat "$TMP/out")"; fi
[ "$(dump_files)" = 1 ] && pass "pending migration: one dump taken" || fail "pending migration: $(dump_files) dumps"
dump="$(find "$BACKUP_DIR" -type f | head -1)"
mode="$(stat -c '%a' "$dump" 2>/dev/null || stat -f '%Lp' "$dump")"
[ "$mode" = 600 ] && pass "pending migration: dump is owner-only (600)" || fail "dump mode is $mode, not 600"
dmode="$(stat -c '%a' "$BACKUP_DIR" 2>/dev/null || stat -f '%Lp' "$BACKUP_DIR")"
[ "$dmode" = 700 ] && pass "pending migration: backup dir is owner-only (700)" || fail "backup dir mode is $dmode, not 700"
gunzip -c "$dump" 2>/dev/null | grep -q "dump complete" \
  && pass "pending migration: dump holds pg_dump output" || fail "pending migration: dump content wrong"

if dumps "" "$DUMP_OK"; then pass "no revision yet (new database): exits 0"; else fail "new database failed: $(cat "$TMP/out")"; fi
[ "$(dump_files)" = 1 ] && pass "no revision yet: dumps anyway (fail safe)" || fail "no revision yet: no dump"

if dumps "abc122" ""; then fail "empty dump accepted"; else pass "empty dump: exits non-zero"; fi
[ "$(dump_files)" = 0 ] && pass "empty dump: no file left behind" || fail "empty dump: file left behind"

if dumps "abc122" $'-- PostgreSQL database dump\nCREATE TA'; then fail "truncated dump accepted"; else pass "truncated dump: exits non-zero"; fi

: > "$CALLS"
if FAKE_CURRENT_FAIL=1 "$server/deploy/pre-migration-dump.sh" > "$TMP/out" 2>&1; then
  fail "unreadable revision accepted"
else
  pass "unreadable revision (e.g. revert without downgrade): exits non-zero"
fi
grep -q "Rollback" "$TMP/out" && pass "unreadable revision: points at the rollback docs" || fail "no rollback pointer: $(cat "$TMP/out")"

# --- backup.sh shares the dump -------------------------------------------------
grep -q 'deploy/pg-dump.sh' "$REPO_ROOT/deploy/backup.sh" \
  && pass "nightly backup uses the same dump script" || fail "backup.sh does not use pg-dump.sh"

if [ "$failures" -gt 0 ]; then
  echo "$failures failure(s)" >&2
  exit 1
fi
echo "all deploy script checks passed"
