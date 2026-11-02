#!/usr/bin/env bash
# `docker compose` for the production stack, run from the repo folder on the
# server. With the APPS_EDGE_* settings unset (the default) this is exactly
#   docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
# With them set it adds deploy/compose.apps-edge.yml, which puts Caddy on the
# shared apps network (DEPLOY.md "Shared apps network"). Use it for anything
# that (re)creates Caddy, such as `up`, or a plain compose call would drop
# Caddy off that network.
set -euo pipefail
cd "$(dirname "$0")/.."
. deploy/apps-edge-env.sh
apps_edge_resolve
files=(-f docker-compose.prod.yml)
[ -n "$APPS_EDGE_NETWORK" ] && files+=(-f deploy/compose.apps-edge.yml)
exec docker compose "${files[@]}" --env-file .env.production "$@"
