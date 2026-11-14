#!/bin/sh
# Writes the production env file from infra/.env.production.example with every
# secret generated (openssl rand). Run once per installation, from anywhere:
#
#   sh scripts/init-secrets.sh                 # writes infra/.env
#   sh scripts/init-secrets.sh /path/to/env    # writes there instead
#   sh scripts/init-secrets.sh --force         # overwrite an existing file
#
# Any variable of the template that is set in your environment is used as is,
# so non-secret values can be given up front:
#
#   KEMUDI_DOMAIN=kemudi.example.com EMAIL_HOST=smtp.example.com \
#     DEFAULT_FROM_EMAIL=kemudi@example.com sh scripts/init-secrets.sh
#
# Never rerun with --force on a live installation: new SECRET_KEY,
# POSTGRES_PASSWORD or KEMUDI_SECRET_KEY values lock you out of existing data
# (docs/backup.md).
set -eu

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
template="$root/infra/.env.production.example"
out="$root/infra/.env"
force=0

for arg in "$@"; do
    case "$arg" in
        --force) force=1 ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        -*) echo "init-secrets: unknown option $arg" >&2; exit 2 ;;
        *) out=$arg ;;
    esac
done

command -v openssl >/dev/null 2>&1 || { echo "init-secrets: openssl is required" >&2; exit 1; }
[ -f "$template" ] || { echo "init-secrets: missing $template" >&2; exit 1; }
if [ -e "$out" ] && [ "$force" -ne 1 ]; then
    echo "init-secrets: $out exists; not overwriting (use --force on a NEW install only)" >&2
    exit 1
fi

# Secrets and how each is generated. Hex only: these values end up in URLs
# (amqp://user:pass@...) where '/', '+' or '=' would break parsing.
gen() {
    case "$1" in
        # Fernet key: 32 random bytes, urlsafe base64 (44 chars).
        KEMUDI_SECRET_KEY) openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n' ;;
        SECRET_KEY) openssl rand -hex 50 ;;
        *) openssl rand -hex 32 ;;
    esac
}

is_secret() {
    case "$1" in
        SECRET_KEY|POSTGRES_PASSWORD|RABBITMQ_PASS|\
        KEMUDI_SECRET_KEY|KEMUDI_HERMES_API_KEY|KEMUDI_AWAK_API_KEY|\
        KEMUDI_RUNNER_KEY|KEMUDI_SVC_KEY|KEMUDI_LLM_PROXY_TOKEN) return 0 ;;
        *) return 1 ;;
    esac
}

umask 077
tmp="$out.tmp.$$"
trap 'rm -f "$tmp"' EXIT INT TERM
: > "$tmp"

generated=0
while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
        [A-Z]*=*)
            key=${line%%=*}
            value=${line#*=}
            case "$key" in *[!A-Z0-9_]*) printf '%s\n' "$line" >> "$tmp"; continue ;; esac
            eval "env_value=\${$key:-}"
            if [ -n "$env_value" ]; then
                value=$env_value
            elif [ -z "$value" ] && is_secret "$key"; then
                value=$(gen "$key")
                generated=$((generated + 1))
            fi
            printf '%s=%s\n' "$key" "$value" >> "$tmp"
            ;;
        *) printf '%s\n' "$line" >> "$tmp" ;;
    esac
done < "$template"

mv "$tmp" "$out"
trap - EXIT INT TERM
chmod 600 "$out"

echo "init-secrets: wrote $out ($generated secrets generated, mode 600)."
missing=""
for key in KEMUDI_DOMAIN EMAIL_HOST DEFAULT_FROM_EMAIL; do
    grep -q "^$key=..*" "$out" || missing="$missing $key"
done
grep -q "^KEMUDI_DOMAIN=kemudi.example.com$" "$out" && missing="$missing KEMUDI_DOMAIN"
[ -z "$missing" ] || echo "init-secrets: now set$missing in $out (compose refuses to start without them)."
echo "init-secrets: keep a copy of $out with your backups (docs/backup.md)."
