# Upgrading Kemudi

Kemudi releases are tagged `vX.Y.Z`; each tag publishes
`ghcr.io/arifnurdiansyah92/kemudi-*:X.Y.Z` and a GitHub Release with the
changes. The commands below assume the install layout from
[install.md](install.md) and use this shorthand:

```sh
alias kemudi='docker compose -f infra/docker-compose.yml --env-file infra/.env'
```

Add the same `--profile ai` / `--profile awak` flags you run with (or set
`COMPOSE_PROFILES`).

## Before you start

1. Read the release notes for every version between yours and the target.
   Breaking changes and new required settings are listed there.
2. **Back up** ([backup.md](backup.md)): the database dump, the media and
   `kemudi-ai-data` volumes, and `infra/.env`. Upgrades are forward-only (see
   below); the backup is your rollback.

## Upgrade

```sh
# 1. Deployment files of the new release (compose file, gateway config).
git fetch --tags
git checkout v1.1.0

# 2. New settings: compare the template with your env file and copy over any
#    new variables (new secrets: generate with `openssl rand -hex 32`).
diff <(grep -o '^[A-Z_]*=' infra/.env.production.example | sort) \
     <(grep -o '^[A-Z_]*=' infra/.env | sort)

# 3. Point at the new images.
sed -i 's/^KEMUDI_VERSION=.*/KEMUDI_VERSION=1.1.0/' infra/.env

# 4. Pull, then recreate what changed.
kemudi pull
kemudi up -d --wait
```

`up -d --wait` returns when every container is healthy again. Expect a short
interruption while `kemudi-back` restarts and migrates.

### What happens on start

- **Database migrations run automatically.** `kemudi-back` runs
  `manage.py migrate` (and reloads the default project templates) every time
  it starts; `kemudi-async` and the gateway wait until it is healthy.
- **The orchestrator updates its own schema on start** (the SQLite database in
  the `kemudi-ai-data` volume: contracts, baselines, Awak configuration and
  vault).
- **Both are forward-only.** There are no down-migrations. Starting an older
  image against a database a newer one has migrated is not supported and may
  fail or corrupt data.

### Rolling back

Rollback means restoring the backup taken before the upgrade:

1. `kemudi down` (keep the volumes for now, in case you need them).
2. Set `KEMUDI_VERSION` back to the old version and `git checkout` the old tag.
3. Restore the database dump and the volumes as in
   [backup.md, "Restore"](backup.md#restore).
4. `kemudi up -d --wait`.

## Static files after an upgrade

`kemudi-static-data` (Django's static files: admin and API browser styles,
e-mail images) is filled from the `kemudi-back` image only when the volume is
first created; Docker never refreshes a non-empty volume. After an upgrade that
changes them, recreate it (it holds no user data):

```sh
kemudi stop kemudi-back kemudi-async kemudi-gateway
kemudi rm -f kemudi-back kemudi-async kemudi-gateway
docker volume rm kemudi_kemudi-static-data
kemudi up -d --wait
```

## Third-party images

PostgreSQL, RabbitMQ, nginx and taiga-protected are pinned to exact versions
in `infra/docker-compose.yml`; a Kemudi release updates the pins when needed.

- **PostgreSQL major versions** (16 -> 17) need a dump and restore: a new major
  version cannot open the old data directory. Dump with the old version, move
  the old `kemudi_kemudi-db-data` volume aside, start the new version on an
  empty volume and restore ([backup.md](backup.md)). Minor versions (16.x)
  upgrade in place.
- **RabbitMQ** holds only transient queues; if a RabbitMQ upgrade refuses the
  old data, stop the stack, remove `kemudi_kemudi-*-rabbitmq-data` and start
  again. Stay below RabbitMQ 4.1: `kemudi-events` cannot connect to it.

## Moving from the development stack

The dev stack (`infra/docker-compose.dev.yml`, project `kemudi-dev`) runs
PostgreSQL 12 and keeps its data in `kemudi-dev_*` volumes. To move that data
into a production install, take a backup of the dev stack as in
[backup.md](backup.md) (substitute `-f infra/docker-compose.dev.yml` and the
`kemudi-dev_` volume prefix), then restore it into the production stack. The
dump and restore also performs the PostgreSQL 12 -> 16 upgrade. Copy the dev
`KEMUDI_SECRET_KEY` and `SECRET_KEY` into the production `infra/.env` before
the first start, or stored keys and signed links stop working.
