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

rsync -az --delete \
  --include '.env.production.example' \
  --exclude '.git' \
  --exclude 'ui/node_modules' \
  --exclude 'ui/dist' \
  --exclude '__pycache__' \
  --exclude '.env' \
  --exclude '.env.*' \
  "$REPO_ROOT/" "$HOST:$REMOTE_DIR/"

ssh "$HOST" "cd $REMOTE_DIR && \
  test -f .env.production || { echo 'ERROR: create .env.production on the server first (see .env.production.example)'; exit 1; } && \
  docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build"

echo "Deployed. Check status with:"
echo "  ssh $HOST 'cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml ps'"
