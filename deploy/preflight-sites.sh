#!/usr/bin/env bash
# Pre-deploy check for the optional extra static sites (DEPLOY.md "Extra static
# sites"). Runs ON THE SERVER from the repo folder; deploy.sh calls it before
# `docker compose up`, so a site file Caddy would reject (or a symlink) fails
# the deploy while the running Caddy keeps serving, rather than stopping the
# new one starting.
set -euo pipefail

cd "$(dirname "$0")/.."
env_value() { sed -n "s/^$1=//p" .env.production | tail -n 1 | tr -d "\"' "; }

DOMAIN="$(env_value DOMAIN)"
[ -n "$DOMAIN" ] || { echo "preflight-sites: DOMAIN missing from .env.production" >&2; exit 1; }
# Same default as docker-compose.prod.yml's mount: ${SITES_DIR:-${HOME}/sites}.
SITES_DIR="$(env_value SITES_DIR)"
SITES_DIR="${SITES_DIR:-$HOME/sites}"
case "$SITES_DIR" in "~/"*) SITES_DIR="$HOME/${SITES_DIR#\~/}" ;; esac

# Created here as the deploy user: if Docker creates a missing bind source, it
# is owned by root and the owner can't copy sites into it.
mkdir -p "$SITES_DIR"

# Caddy follows symlinks, so one in the sites folder could serve any file in
# the container, e.g. the TLS keys under /data. Refuse them all.
links="$(find "$SITES_DIR" -type l)"
if [ -n "$links" ]; then
  echo "preflight-sites: symlinks are not allowed in $SITES_DIR; remove them:" >&2
  echo "$links" >&2
  exit 1
fi

# Validate with the base image the caddy service is built FROM (same Caddy
# binary; the built image doesn't exist until `up --build`). --network none:
# validation needs no network and can't clash with the edge network's pinned IP.
IMAGE="$(sed -n 's/^FROM \(caddy:[^ ]*\).*/\1/p' deploy/ui.Dockerfile)"
[ -n "$IMAGE" ] || { echo "preflight-sites: no caddy base image in deploy/ui.Dockerfile" >&2; exit 1; }

if ! output="$(docker run --rm --network none -e DOMAIN="$DOMAIN" \
  -v "$PWD/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$SITES_DIR:/sites:ro" \
  "$IMAGE" caddy validate --config /etc/caddy/Caddyfile 2>&1)"; then
  echo "$output" | tail -n 5 >&2
  echo "preflight-sites: Caddy rejects the site files in $SITES_DIR; fix or remove the failing file." >&2
  exit 1
fi
echo "preflight-sites ok: $SITES_DIR"
