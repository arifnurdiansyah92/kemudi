# Backing up and restoring Kemudi

A complete Kemudi backup has four parts. Missing any one of them loses data.

| Part | Where | Holds |
| --- | --- | --- |
| Database dump | `kemudi-db` (PostgreSQL) | Projects, stories, tasks, users, comments, history. |
| Media | volume `kemudi_kemudi-media-data` | Attachments, avatars, project exports. |
| Kemudi AI data | volume `kemudi_kemudi-ai-data` | Contracts and baselines, backtests, Awak configuration, the vault (encrypted project secrets), generated SSH keys, BYOK model keys, Awak's repository clones. **Confidential.** |
| Settings | `infra/.env` | Every secret, including `KEMUDI_SECRET_KEY` and `SECRET_KEY`. |

**`KEMUDI_SECRET_KEY` must be kept.** It is the Fernet key that encrypts the
SSH keys, BYOK model keys and vault entries in `kemudi-ai-data`. A restore
with a different key brings those rows back unreadable; there is no recovery
other than regenerating every key. `SECRET_KEY` signs sessions and media links;
a different one logs everyone out. Store `infra/.env` with the backup, or
separately in a password manager, and encrypt the backup (it contains
contracts and keys).

If you run the Awak profile, also back up `kemudi_kemudi-awak-skills` (uploaded
and fetched skill files). The other volumes (`kemudi-static-data`, RabbitMQ,
`kemudi-hermes-data`, `kemudi-awak-*` workspaces and profiles, Docker-in-Docker
data, pnpm cache) are rebuilt automatically and need no backup.

The commands assume the install layout from [install.md](install.md), the
default project name `kemudi` (volume prefix `kemudi_`), and:

```sh
alias kemudi='docker compose -f infra/docker-compose.yml --env-file infra/.env'
```

## Backup

Run from the directory that holds `infra/`. The archive tool is a pinned
`alpine` image; any image with `tar` works.

```sh
set -eu
b=backups/kemudi-$(date +%Y%m%d-%H%M%S)
mkdir -p "$b"

# 1. Database: a consistent dump while Kemudi runs (custom format).
kemudi exec -T kemudi-db sh -c 'pg_dump -U "$POSTGRES_USER" -d taiga -Fc' > "$b/kemudi-db.dump"

# 2. Media: files are written once and never modified, so a live copy is safe.
docker run --rm -v kemudi_kemudi-media-data:/v:ro -v "$PWD/$b":/backup alpine:3.22.8 \
    tar czf /backup/media.tgz -C /v .

# 3. Kemudi AI data: a SQLite database, so stop the orchestrator for the copy
#    (a few seconds; the AI features answer 502 meanwhile).
kemudi stop kemudi-orchestrator
docker run --rm -v kemudi_kemudi-ai-data:/v:ro -v "$PWD/$b":/backup alpine:3.22.8 \
    tar czf /backup/kemudi-ai-data.tgz -C /v .
kemudi start kemudi-orchestrator

# 4. Settings.
cp infra/.env "$b/env"
chmod -R go-rwx "$b"
```

Then copy `$b` off the host (encrypted), and check that the dump is readable:

```sh
docker run --rm -v "$PWD/$b":/backup postgres:16.16-alpine \
    pg_restore --list /backup/kemudi-db.dump | head
```

Schedule it (cron, systemd timer) and keep several generations. A backup you
have never restored is a hope, not a backup: run the restore below on a spare
host now and then.

## Restore

On a new host (or after `kemudi down -v` on the old one), with the same
release checked out as in [install.md](install.md) steps 1 and 3:

```sh
set -eu
b=backups/kemudi-20261114-120000          # the backup to restore

# 1. Settings from the backup: the same secrets, above all KEMUDI_SECRET_KEY.
cp "$b/env" infra/.env && chmod 600 infra/.env

# 2. Create the containers and volumes without starting the apps, then start
#    only the database.
kemudi create
kemudi up -d --wait kemudi-db

# 3. Database.
kemudi exec -T kemudi-db sh -c \
    'pg_restore -U "$POSTGRES_USER" -d taiga --clean --if-exists --no-owner --exit-on-error' \
    < "$b/kemudi-db.dump"

# 4. Volumes.
docker run --rm -v kemudi_kemudi-media-data:/v -v "$PWD/$b":/backup:ro alpine:3.22.8 \
    sh -c 'rm -rf /v/* && tar xzf /backup/media.tgz -C /v'
docker run --rm -v kemudi_kemudi-ai-data:/v -v "$PWD/$b":/backup:ro alpine:3.22.8 \
    sh -c 'rm -rf /v/* && tar xzf /backup/kemudi-ai-data.tgz -C /v'

# 5. Start everything (migrations are a no-op unless the release is newer).
kemudi up -d --wait
```

Check the result:

```sh
curl -fsS http://127.0.0.1:8080/api/kemudi/health
```

Then sign in, open a project with attachments and download one, and open a
project's contract (Kemudi AI) to confirm both volumes came back. If you use
Awak, open Project settings -> Agent: the deploy keys must show their public
keys; an error there means `KEMUDI_SECRET_KEY` does not match the backup.

Restoring into a newer release is fine (step 5 migrates forward). Restoring
into an older release is not supported (see [upgrade.md](upgrade.md)).
