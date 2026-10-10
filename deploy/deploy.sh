#!/usr/bin/env bash
# Sync the repo to the VPS and (re)build/restart the production stack.
# Usage: ./deploy/deploy.sh <ssh-host>   (or set DEPLOY_HOST)
set -euo pipefail

HOST="${1:-${DEPLOY_HOST:-}}"
if [ -z "$HOST" ]; then
  echo "Usage: ./deploy/deploy.sh <ssh-host>   (an ~/.ssh/config alias or user@ip)" >&2
  echo "Or set DEPLOY_HOST in your environment." >&2
  exit 1
fi
REMOTE_DIR="finance-tracker"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Ship exactly the commit being deployed. A modified, staged or untracked file
# would otherwise reach the server unreviewed (rsync copies the working tree),
# so refuse before anything leaves this machine. Ignored files (.env,
# node_modules) never ship either: only `git archive HEAD` is synced.
dirty="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
if [ -n "$dirty" ]; then
  echo "deploy: refusing to deploy a dirty working tree. Commit, stash or remove:" >&2
  echo "$dirty" >&2
  exit 1
fi
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
git -C "$REPO_ROOT" archive HEAD | tar -x -C "$STAGE"

# The excludes also protect server-only files (.env.production) from --delete.
rsync -az --delete \
  --include '.env.production.example' \
  --exclude '.git' \
  --exclude 'ui/node_modules' \
  --exclude 'ui/dist' \
  --exclude '__pycache__' \
  --exclude '.env' \
  --exclude '.env.*' \
  "$STAGE/" "$HOST:$REMOTE_DIR/"

# preflight-sites.sh: creates the extra sites folder (else Docker creates it
# root-owned) and validates it, so a broken site file fails the deploy while
# the running Caddy keeps serving, instead of stopping the new one starting.
# pre-migration-dump.sh: when the new code has a migration the database hasn't
# run, dumps the database first and stops the deploy if the dump is empty
# (DEPLOY.md "Rollback"). It also stops a deploy whose code can't read the
# database's revision, e.g. a revert of a migration that wasn't downgraded.
# --remove-orphans: a service dropped from the compose file must not keep
# running on its last image (the retired background-sync worker did, for
# months, after per-user encryption removed it).
ssh "$HOST" "cd $REMOTE_DIR && \
  test -f .env.production || { echo 'ERROR: create .env.production on the server first (see .env.production.example)'; exit 1; } && \
  ./deploy/preflight-sites.sh && \
  ./deploy/pre-migration-dump.sh && \
  docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --remove-orphans && \
  ./deploy/smoke.sh"

echo "Deployed. Check status with:"
echo "  ssh $HOST 'cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml ps'"
