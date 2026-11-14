#!/bin/sh
# Smoke test of a running production stack (infra/docker-compose.yml): creates
# a superuser, signs in through the gateway, and checks the API, the Kemudi AI
# service and the web UI. Used by .github/workflows/smoke.yml; also handy after
# an install or upgrade.
#
#   sh scripts/smoke-test.sh <base-url> [docker compose args...]
#
#   sh scripts/smoke-test.sh http://127.0.0.1:9200 \
#       -p kemudi-prodtest -f infra/docker-compose.yml --env-file /tmp/kemudi.env
#
# The superuser is "smoke-admin" (SMOKE_USER / SMOKE_PASSWORD override it);
# only use this on a stack you are allowed to add a user to.
set -eu

base=${1:?usage: smoke-test.sh <base-url> [docker compose args...]}
shift
user=${SMOKE_USER:-smoke-admin}
password=${SMOKE_PASSWORD:-$(openssl rand -hex 16)}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

fail() { echo "smoke: FAIL: $*" >&2; exit 1; }
step() { echo "smoke: $*"; }

step "create superuser $user"
docker compose "$@" exec -T -e DJANGO_SUPERUSER_PASSWORD="$password" kemudi-back \
    python manage.py createsuperuser --noinput --username "$user" \
    --email "$user@example.invalid" >/dev/null 2>"$tmp/err" \
    || grep -q "already" "$tmp/err" \
    || { cat "$tmp/err" >&2; fail "createsuperuser"; }
if grep -q "already" "$tmp/err"; then
    # A rerun: give the existing smoke user this run's password.
    step "$user exists; resetting its password"
    docker compose "$@" exec -T -e SMOKE_USER="$user" -e SMOKE_PASSWORD="$password" kemudi-back \
        python manage.py shell -c "import os
from django.contrib.auth import get_user_model
u = get_user_model().objects.get(username=os.environ['SMOKE_USER'])
u.set_password(os.environ['SMOKE_PASSWORD'])
u.save()" >/dev/null || fail "password reset"
fi

step "POST /api/v1/auth"
code=$(curl -sS -o "$tmp/auth.json" -w '%{http_code}' -H 'Content-Type: application/json' \
    -d "{\"type\":\"normal\",\"username\":\"$user\",\"password\":\"$password\"}" \
    "$base/api/v1/auth")
[ "$code" = 200 ] || { cat "$tmp/auth.json" >&2; fail "auth answered $code"; }
token=$(sed -n 's/.*"auth_token": *"\([^"]*\)".*/\1/p' "$tmp/auth.json")
[ -n "$token" ] || fail "no auth_token in the auth response"

step "GET /api/v1/users/me"
code=$(curl -sS -o "$tmp/me.json" -w '%{http_code}' -H "Authorization: Bearer $token" "$base/api/v1/users/me")
[ "$code" = 200 ] || fail "users/me answered $code"

step "GET /api/kemudi/health"
code=$(curl -sS -o "$tmp/health.json" -w '%{http_code}' "$base/api/kemudi/health")
if [ "$code" != 200 ] || ! grep -q '"ok": *true' "$tmp/health.json"; then
    fail "orchestrator health answered $code: $(cat "$tmp/health.json")"
fi

step "GET /api/kemudi/me (orchestrator -> kemudi-back with the token)"
code=$(curl -sS -o "$tmp/kme.json" -w '%{http_code}' -H "Authorization: Bearer $token" "$base/api/kemudi/me")
if [ "$code" != 200 ] || ! grep -q "\"username\": *\"$user\"" "$tmp/kme.json"; then
    fail "/api/kemudi/me answered $code: $(cat "$tmp/kme.json")"
fi

step "GET / (web UI)"
code=$(curl -sS -o "$tmp/index.html" -D "$tmp/index.h" -w '%{http_code}' "$base/")
[ "$code" = 200 ] || fail "/ answered $code"
grep -qi '^content-type: *text/html' "$tmp/index.h" || fail "/ is not text/html"
grep -qi '<html' "$tmp/index.html" || fail "/ has no <html>"
grep -qi '^x-frame-options: *SAMEORIGIN' "$tmp/index.h" || fail "/ lacks X-Frame-Options"
grep -qi '^x-content-type-options: *nosniff' "$tmp/index.h" || fail "/ lacks X-Content-Type-Options"

step "GET /admin/ is closed"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$base/admin/")
[ "$code" = 404 ] || fail "/admin/ answered $code, expected 404"

step "GET /api/kemudi/llm/ is closed"
code=$(curl -sS -o /dev/null -w '%{http_code}' "$base/api/kemudi/llm/v1/models")
[ "$code" = 404 ] || fail "/api/kemudi/llm/ answered $code, expected 404"

step "OK"
