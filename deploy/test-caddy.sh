#!/usr/bin/env bash
# Checks the production Caddyfile with the real Caddy image, so a config that
# Caddy would reject can never reach the auto-deploy. Covers the optional
# extra static sites folder (see DEPLOY.md): empty, absent, the documented
# example, a broken site file (which must fail), and the headers a site gets
# from the shared `static_site` snippet when actually served.
# Usage: ./deploy/test-caddy.sh   (needs Docker; CI runs it in test.yml)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Same image the production Caddy is built from, so the two can't drift.
IMAGE="$(sed -n 's/^FROM \(caddy:[^ ]*\).*/\1/p' "$REPO_ROOT/deploy/ui.Dockerfile")"
[ -n "$IMAGE" ] || { echo "FAIL: no caddy base image in deploy/ui.Dockerfile" >&2; exit 1; }
CADDYFILE="$REPO_ROOT/deploy/Caddyfile"
EXAMPLE_DIR="$REPO_ROOT/docs/extra-sites"
TMP="$(mktemp -d)"
CONTAINER="caddy-test-$$"
cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT

failures=0
pass() { echo "ok   - $1"; }
fail() { echo "FAIL - $1" >&2; failures=$((failures + 1)); }

# caddy <sites-dir|""> <caddy args...> — runs the Caddy CLI against the real
# Caddyfile, with the sites folder mounted read-only where prod mounts it.
caddy() {
  local sites="$1"; shift
  local mount=()
  [ -n "$sites" ] && mount=(-v "$sites:/sites:ro")
  docker run --rm -e DOMAIN=nilu.test -v "$CADDYFILE:/etc/caddy/Caddyfile:ro" \
    ${mount[@]+"${mount[@]}"} "$IMAGE" caddy "$@" --config /etc/caddy/Caddyfile 2>&1
}
validates() { caddy "$1" validate >/dev/null; }
adapted() { caddy "$1" adapt; }

docker pull -q "$IMAGE" >/dev/null

# --- Compose wiring -----------------------------------------------------------
# The sites folder must be mounted read-only at /sites, from ~/sites by default
# (outside the rsync --delete target) or from SITES_DIR when set.

# sites_mount [SITES_DIR] — the caddy service's /sites mount as "<source> <read_only>".
sites_mount() {
  env -u SITES_DIR ${1:+SITES_DIR="$1"} \
    DOMAIN=x POSTGRES_USER=x POSTGRES_PASSWORD=x SECRET_KEY=x ENCRYPTION_KEY=x \
    TRUELAYER_CLIENT_ID= TRUELAYER_CLIENT_SECRET= \
    docker compose -f "$REPO_ROOT/docker-compose.prod.yml" --env-file /dev/null config --format json \
    | python3 -c '
import json, sys
vols = json.load(sys.stdin)["services"]["caddy"].get("volumes", [])
print(*[v["source"] + " " + str(v.get("read_only", False)) for v in vols if v["target"] == "/sites"])'
}
got="$(sites_mount)"
[ "$got" = "$HOME/sites True" ] \
  && pass "sites folder defaults to ~/sites, read-only" || fail "default sites mount: '$got'"
got="$(sites_mount /srv/other-sites)"
[ "$got" = "/srv/other-sites True" ] \
  && pass "SITES_DIR overrides the sites folder" || fail "SITES_DIR sites mount: '$got'"

# --- Config validation -------------------------------------------------------

mkdir -p "$TMP/empty"
validates "$TMP/empty" && pass "valid with an empty sites folder" || fail "invalid with an empty sites folder"
validates "" && pass "valid with no sites folder mounted" || fail "invalid with no sites folder mounted"

hosts="$(adapted "$TMP/empty" | grep -o '"host":\[[^]]*\]' | sort -u)"
[ "$hosts" = '"host":["nilu.test"]' ] \
  && pass "empty sites folder serves only the main domain" \
  || fail "empty sites folder changed the served hosts: $hosts"

cp -R "$EXAMPLE_DIR" "$TMP/example"
validates "$TMP/example" && pass "valid with the documented example site" || fail "invalid with the documented example site"
adapted "$TMP/example" | grep -q '"host":\["example.com"\]' \
  && pass "example site's host is served" || fail "example site's host missing from config"

# Self-test: the check must catch a broken site file, or the passes above mean nothing.
mkdir -p "$TMP/broken" && echo 'broken.example.com { not_a_directive }' > "$TMP/broken/broken.caddy"
validates "$TMP/broken" && fail "a broken site file was accepted" || pass "a broken site file is rejected"

# --- Behaviour of a served site ---------------------------------------------
# Serve the example's content on plain HTTP inside the container (no ACME, no
# host ports) through the same snippet, and inspect real responses.

mkdir -p "$TMP/live" && cp -R "$EXAMPLE_DIR/example" "$TMP/live/example"
mkdir -p "$TMP/live/example/no-index" && echo x > "$TMP/live/example/no-index/file.txt"
echo secret > "$TMP/live/example/.hidden"
cat > "$TMP/live/probe.caddy" <<'EOF'
http://probe.test:8081 {
	import static_site example
}
http://indexed.test:8081 {
	import static_site example
	header X-Robots-Tag "all"
}
http://apex.test:8081 {
	import static_site example
	header Strict-Transport-Security "max-age=31536000"
}
EOF
# The CSP override documented (commented out) in the example, used verbatim.
CSP_OVERRIDE="$(sed -n 's/^[[:space:]]*# *\(header Content-Security-Policy .*\)$/\1/p' "$EXAMPLE_DIR/example.caddy")"
[ -n "$CSP_OVERRIDE" ] || fail "example.caddy documents no CSP override line"
printf 'http://inline.test:8081 {\n\timport static_site example\n\t%s\n}\n' "$CSP_OVERRIDE" >> "$TMP/live/probe.caddy"

docker run -d --name "$CONTAINER" -e DOMAIN=localhost \
  -v "$CADDYFILE:/etc/caddy/Caddyfile:ro" -v "$TMP/live:/sites:ro" "$IMAGE" >/dev/null

# headers <host> <path> [extra header lines] — response status line and headers.
# Raw HTTP over nc: busybox wget prints no headers for error responses, which
# would make every assertion about a 404 vacuous.
headers() {
  local host="$1" path="$2"; shift 2
  local request="GET $path HTTP/1.1\r\nHost: $host\r\nConnection: close\r\n"
  for extra in "$@"; do request="$request$extra\r\n"; done
  docker exec "$CONTAINER" sh -c "printf '$request\r\n' | nc 127.0.0.1 8081" 2>&1 \
    | LC_ALL=C sed '/^\r*$/q' | tr -d '\r' || true
}
for _ in $(seq 1 30); do headers probe.test / | grep -q 'HTTP/1.1 200' && break; sleep 0.5; done

page="$(headers probe.test /)"
expect_header() { # <description> <regex>
  echo "$page" | grep -qiE "$2" && pass "$1" || fail "$1 (got: $(echo "$page" | tr '\n' ' '))"
}
expect_header "page is served"                 'HTTP/1.1 200'
expect_header "HSTS"                           'Strict-Transport-Security: max-age=[0-9]+'
expect_header "nosniff"                        'X-Content-Type-Options: nosniff'
expect_header "frame denial"                   'X-Frame-Options: DENY'
expect_header "Referrer-Policy"                'Referrer-Policy: strict-origin-when-cross-origin'
expect_header "Permissions-Policy"             'Permissions-Policy: .*camera=\(\)'
expect_header "CSP defaults to self"           "Content-Security-Policy: default-src 'self'"
expect_header "CSP forbids framing"            "Content-Security-Policy: .*frame-ancestors 'none'"
expect_header "CSP forbids form posts"         "Content-Security-Policy: .*form-action 'none'"
expect_header "CSP allows Google Fonts CSS"    'Content-Security-Policy: .*style-src [^;]*https://fonts.googleapis.com'
expect_header "CSP allows Google Fonts files"  'Content-Security-Policy: .*font-src [^;]*https://fonts.gstatic.com'
expect_header "not indexed by default"         'X-Robots-Tag: noindex'
expect_header "HTML is revalidated"            'Cache-Control: no-cache'

page="$(headers indexed.test /)"
expect_header "X-Robots-Tag can be overridden" 'X-Robots-Tag: all'

page="$(headers apex.test /)"
if echo "$page" | grep -q 'Strict-Transport-Security: max-age=31536000$' \
  && [ "$(echo "$page" | grep -ci 'Strict-Transport-Security:')" = 1 ]; then
  pass "HSTS can drop includeSubDomains for an apex domain"
else
  fail "HSTS override (got: $(echo "$page" | grep -i 'Strict-Transport' | tr '\n' ' '))"
fi

page="$(headers inline.test /)"
expect_header "CSP override allows inline"     "Content-Security-Policy: .*script-src 'self' 'unsafe-inline'"
expect_header "CSP override keeps framing ban" "Content-Security-Policy: .*frame-ancestors 'none'"
expect_header "CSP override keeps form ban"    "Content-Security-Policy: .*form-action 'none'"
csp_count="$(echo "$page" | grep -ci 'Content-Security-Policy:' || true)"
[ "$csp_count" = 1 ] && pass "CSP override sends one CSP header" || fail "CSP override sent $csp_count CSP headers"

page="$(headers probe.test /style.css)"
expect_header "assets are cached"              'Cache-Control: public, max-age=[1-9]'
page="$(headers probe.test /not-uploaded-yet.css)"
if echo "$page" | grep -q 'HTTP/1.1 404' && ! echo "$page" | grep -qi 'Cache-Control:.*max-age'; then
  pass "404s are not cached"
else
  fail "404s are not cached (got: $(echo "$page" | tr '\n' ' '))"
fi

page="$(headers probe.test / 'Accept-Encoding: gzip')"
expect_header "gzip"                           'Content-Encoding: gzip'
page="$(headers probe.test / 'Accept-Encoding: zstd')"
expect_header "zstd"                           'Content-Encoding: zstd'

page="$(headers probe.test /no-index/)"
expect_header "no directory listing"           'HTTP/1.1 404'
page="$(headers probe.test /.hidden)"
expect_header "dotfiles are not served"        'HTTP/1.1 404'

# --- Reload (the zero-downtime step DEPLOY.md documents) ----------------------

reload() { docker exec "$CONTAINER" caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1; }
printf 'http://added.test:8081 {\n\timport static_site example\n}\n' > "$TMP/live/added.caddy"
reload && pass "reload succeeds after adding a site" || fail "reload failed after adding a site"
page="$(headers added.test /)"
expect_header "added site is served after reload" 'HTTP/1.1 200'

echo 'broken.test { not_a_directive }' > "$TMP/live/broken.caddy"
reload && fail "reload accepted a broken site file" || pass "reload rejects a broken site file"
page="$(headers probe.test /)"
expect_header "running sites keep serving after a rejected reload" 'HTTP/1.1 200'

# --- Pre-deploy check (deploy/preflight-sites.sh, run by deploy.sh before `up`) ---
# Mirrors the server: HOME is $SERVER, the repo copy (deploy/, the prod compose
# file and a fake .env.production) is ~/finance-tracker, the sites sit beside it.

SERVER="$TMP/server" && DEPLOYED="$SERVER/finance-tracker" && mkdir -p "$DEPLOYED"
DOCKER_CLI_CONFIG="${DOCKER_CONFIG:-$HOME/.docker}"  # docker's context, before HOME moves
cp -R "$REPO_ROOT/deploy" "$DEPLOYED/deploy" && cp "$REPO_ROOT/docker-compose.prod.yml" "$DEPLOYED/"
# preflight_env <SITES_DIR line exactly as written in .env.production> — runs
# the check quietly and returns its status.
preflight_env() {
  printf 'DOMAIN=nilu.test\nPOSTGRES_USER=x\nPOSTGRES_PASSWORD=x\nSECRET_KEY=x\nENCRYPTION_KEY=x\n%s\n' "$1" \
    > "$DEPLOYED/.env.production"
  (cd "$DEPLOYED" && HOME="$SERVER" DOCKER_CONFIG="$DOCKER_CLI_CONFIG" \
    ./deploy/preflight-sites.sh >/dev/null 2>&1)
}
# preflight [SITES_DIR value] — the same, with a plain SITES_DIR=<value> line.
preflight() { preflight_env "${1:+SITES_DIR=$1}"; }
preflight && [ -d "$SERVER/sites" ] \
  && pass "preflight creates a missing default ~/sites and passes empty" || fail "preflight with the default folder"
preflight "$SERVER/custom" && [ -d "$SERVER/custom" ] \
  && pass "preflight creates a missing SITES_DIR" || fail "preflight with SITES_DIR"
cp -R "$EXAMPLE_DIR/." "$SERVER/custom/"
preflight "$SERVER/custom" && pass "preflight passes the example site" || fail "preflight rejected the example site"
echo 'broken.example.com { not_a_directive }' > "$SERVER/custom/broken.caddy"
preflight "$SERVER/custom" && fail "preflight accepted a broken site file" || pass "preflight rejects a broken site file"
rm "$SERVER/custom/broken.caddy"
printf 'nilu.test {\n\timport static_site example\n}\n' > "$SERVER/custom/hijack.caddy"
preflight "$SERVER/custom" && fail "preflight accepted a site redefining DOMAIN" \
  || pass "preflight rejects a site redefining the app's domain"
rm "$SERVER/custom/hijack.caddy"
# Caddy follows symlinks, so a link in a site folder could serve anything in
# the container, such as nilu.'s TLS keys under /data.
ln -s /data "$SERVER/custom/example/keys"
preflight "$SERVER/custom" && fail "preflight accepted a symlink in a site folder" \
  || pass "preflight rejects a symlink in a site folder"
rm "$SERVER/custom/example/keys"
ln -s "$SERVER/custom/example.caddy" "$SERVER/custom/linked.caddy"
preflight "$SERVER/custom" && fail "preflight accepted a symlinked site file" \
  || pass "preflight rejects a symlinked site file"
rm "$SERVER/custom/linked.caddy"
preflight "$SERVER/custom" && pass "preflight passes again once the links are gone" \
  || fail "preflight still fails after removing the links"

# The preflight must check the folder compose actually mounts, which expands
# variables and quotes in .env.production. A broken file there must be caught.
preflight '${HOME}/fresh' && [ -d "$SERVER/fresh" ] \
  && pass "preflight creates SITES_DIR=\${HOME}/fresh where compose will mount it" \
  || fail "preflight with SITES_DIR=\${HOME}/fresh"
mkdir -p "$SERVER/x" && echo 'broken.example.com { nope }' > "$SERVER/x/broken.caddy"
preflight '${HOME}/x' && fail "preflight missed a broken file in SITES_DIR=\${HOME}/x" \
  || pass "preflight checks SITES_DIR with variables expanded as compose does"
mkdir -p "$SERVER/with space" && cp -R "$EXAMPLE_DIR/." "$SERVER/with space/"
preflight "\"$SERVER/with space\"" && pass "preflight passes a SITES_DIR containing a space" \
  || fail "preflight with a SITES_DIR containing a space"
echo 'broken.example.com { nope }' > "$SERVER/with space/broken.caddy"
preflight "\"$SERVER/with space\"" && fail "preflight missed a broken file in a SITES_DIR with a space" \
  || pass "preflight checks a SITES_DIR containing a space"
# Other .env syntax compose accepts: an export prefix, an inline comment.
mkdir -p "$SERVER/linked" && ln -s /data "$SERVER/linked/keys"
preflight_env "export SITES_DIR=$SERVER/linked" && fail "preflight missed a symlink under 'export SITES_DIR='" \
  || pass "preflight checks an 'export SITES_DIR=' folder"
preflight_env "SITES_DIR=$SERVER/linked # extra sites" && fail "preflight missed a symlink under an inline comment" \
  || pass "preflight checks a SITES_DIR with an inline comment"
preflight 'relative/sites' && fail "preflight accepted a relative SITES_DIR" \
  || pass "preflight refuses a relative SITES_DIR"
preflight './sites' && fail "preflight accepted a SITES_DIR inside the repo folder" \
  || pass "preflight refuses a SITES_DIR inside the repo folder (rsync --delete wipes it)"

# deploy.sh must run the check, and only bring the stack up if it passes.
deploy_cmd="$(tr -d '\n\\' < "$REPO_ROOT/deploy/deploy.sh")"
echo "$deploy_cmd" | grep -qE '\./deploy/preflight-sites\.sh &&[[:space:]]*docker compose [^&]* up ' \
  && pass "deploy.sh validates sites before compose up" || fail "deploy.sh does not gate compose up on preflight-sites.sh"

if [ "$failures" -gt 0 ]; then
  echo "$failures Caddy check(s) failed" >&2
  exit 1
fi
echo "All Caddy checks passed"
