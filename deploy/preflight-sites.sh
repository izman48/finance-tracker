#!/usr/bin/env bash
# Pre-deploy check for the optional extra static sites (DEPLOY.md "Extra static
# sites"). Runs ON THE SERVER from the repo folder; deploy.sh calls it before
# `docker compose up`, so a site file Caddy would reject (or a symlink) fails
# the deploy while the running Caddy keeps serving, rather than stopping the
# new one starting.
set -euo pipefail

cd "$(dirname "$0")/.."

# Ask compose what it will mount and which DOMAIN Caddy gets, rather than
# parsing .env.production here: compose expands variables, quotes, `export`
# and inline comments, and any disagreement would check the wrong folder.
resolved="$(docker compose -f docker-compose.prod.yml --env-file .env.production config --format json \
  | python3 -c '
import json, sys
caddy = json.load(sys.stdin)["services"]["caddy"]
mounts = [v["source"] for v in caddy.get("volumes", []) if v.get("target") == "/sites"]
print(mounts[0] if len(mounts) == 1 else "")
print(caddy.get("environment", {}).get("DOMAIN") or "")
')" || { echo "preflight-sites: could not read the compose config" >&2; exit 1; }
SITES_DIR="$(echo "$resolved" | sed -n 1p)"
DOMAIN="$(echo "$resolved" | sed -n 2p)"
[ -n "$DOMAIN" ] || { echo "preflight-sites: caddy has no DOMAIN in the compose config" >&2; exit 1; }
case "$SITES_DIR" in
  /*) ;;
  *) echo "preflight-sites: the /sites mount source must be an absolute path, got '$SITES_DIR'" >&2; exit 1 ;;
esac

# Created here as the deploy user: if Docker creates a missing bind source, it
# is owned by root and the owner can't copy sites into it.
mkdir -p "$SITES_DIR"

# Inside the repo folder, every deploy's rsync --delete would wipe the sites.
repo="$(pwd -P)"
case "$(cd "$SITES_DIR" && pwd -P)/" in
  "$repo/"*) echo "preflight-sites: $SITES_DIR is inside $repo, which each deploy wipes; set SITES_DIR outside it" >&2; exit 1 ;;
esac

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
