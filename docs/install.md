# Installing Kemudi

This guide installs a Kemudi release on one Linux server with Docker Compose,
using the published images (`ghcr.io/arifnurdiansyah92/kemudi-*`). For a
development checkout, use `infra/docker-compose.dev.yml` instead (see the
README).

Related: [upgrade.md](upgrade.md), [backup.md](backup.md).

## Requirements

- Linux x86_64 (amd64). The images are not built for arm64 yet.
- Docker Engine 24+ with the Compose plugin v2.24+ (`docker compose version`).
- `openssl` and a POSIX shell (for `scripts/init-secrets.sh`).
- Memory: 4 GB RAM for the core stack. The experimental Awak profile needs
  about 12 GB more (its containers are capped at 2 + 4 + 5 + 1 GB).
- Disk: 10 GB for images and data to start; the Awak profile adds ~10 GB of
  images and whatever its sandboxed Docker builds.
- A DNS name for Kemudi and a TLS certificate (or a reverse proxy that obtains
  one, such as Caddy or Traefik).
- An SMTP account for invitations, password resets and notifications.
- Optional: an OpenAI-compatible model endpoint and key for the AI features.

## 1. Get the deployment files

Only the `infra/` and `scripts/` folders are needed; no source is built.
Download the release you want (the tag is the version):

```sh
git clone --depth 1 --branch v1.1.0 https://github.com/arifnurdiansyah92/kemudi.git
cd kemudi
```

Submodules are not needed for a production install.

## 2. Generate the secrets

```sh
sh scripts/init-secrets.sh
```

This writes `infra/.env` (mode 600) from `infra/.env.production.example`,
generating every secret with `openssl rand`: database and queue passwords,
`SECRET_KEY`, `KEMUDI_SECRET_KEY` (the Fernet key that encrypts stored SSH and
model keys) and the internal service keys. It refuses to overwrite an existing
file. Values can be passed up front:

```sh
KEMUDI_DOMAIN=kemudi.example.com EMAIL_HOST=smtp.example.com \
  DEFAULT_FROM_EMAIL=kemudi@example.com sh scripts/init-secrets.sh
```

Then edit `infra/.env`:

| Setting | What to set |
| --- | --- |
| `KEMUDI_DOMAIN` | The host users open, e.g. `kemudi.example.com` (add `:port` if not 80/443). |
| `KEMUDI_SCHEME` | `https` (behind TLS). `http` only for a local trial. |
| `KEMUDI_BIND`, `KEMUDI_HTTP_PORT` | Where the gateway listens. Default `127.0.0.1:8080`, for a reverse proxy on the same host. |
| `EMAIL_*`, `DEFAULT_FROM_EMAIL` | Your SMTP server. `EMAIL_USE_TLS=True` for port 587, `EMAIL_USE_SSL=True` for 465. |
| `KEMUDI_AI_BASE_URL`, `KEMUDI_AI_API_KEY`, `KEMUDI_AI_MODEL` | Model provider for the AI features (optional). |
| `PUBLIC_REGISTER_ENABLED` | `True` lets anyone sign up. Default `False` (admins invite users). |

Compose refuses to start while any required value is empty
(`required variable ... is missing a value`), so a forgotten secret cannot
start a stack with a blank password.

**Copy `infra/.env` to your password manager or backup now.** Losing
`KEMUDI_SECRET_KEY` makes every stored SSH key and BYOK model key unreadable;
losing `SECRET_KEY` logs everyone out and breaks signed media links
([backup.md](backup.md)).

## 3. TLS

The gateway speaks plain HTTP on `KEMUDI_BIND:KEMUDI_HTTP_PORT` (loopback by
default). Put a TLS reverse proxy in front of it that:

- forwards to `http://127.0.0.1:8080`,
- sets `X-Forwarded-Proto: https` (and `X-Forwarded-For`),
- supports WebSocket upgrades on `/events`,
- allows request bodies of 100 MB (attachments),
- sends `Strict-Transport-Security` once you are sure every user reaches
  Kemudi over https.

Caddy does all of this with two lines:

```caddyfile
kemudi.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

With nginx on the host:

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name kemudi.example.com;
    ssl_certificate     /etc/letsencrypt/live/kemudi.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kemudi.example.com/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;  # map in http {}
        proxy_read_timeout 1h;
    }
}
```

To terminate TLS in the Kemudi gateway itself instead, follow the commented
server blocks at the end of `infra/gateway/kemudi.prod.conf`.

For a trial without TLS, set `KEMUDI_SCHEME=http`,
`SESSION_COOKIE_SECURE=False`, `CSRF_COOKIE_SECURE=False`, and
`KEMUDI_DOMAIN=localhost:8080`.

## 4. Start

```sh
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --wait
```

The first start applies every database migration (one to three minutes);
`--wait` returns once every container reports healthy. Check with:

```sh
docker compose -f infra/docker-compose.yml --env-file infra/.env ps
curl -fsS http://127.0.0.1:8080/api/kemudi/health    # {"ok":true}
```

Tip: `alias kemudi='docker compose -f infra/docker-compose.yml --env-file infra/.env'`
shortens every command below to `kemudi ...`.

## 5. First admin

```sh
docker compose -f infra/docker-compose.yml --env-file infra/.env exec kemudi-back \
    python manage.py createsuperuser
```

Sign in at `https://kemudi.example.com` with that user.

The Django admin (`/admin/`) is closed at the gateway in production. Manage
users through the web UI and `manage.py`; to open `/admin/` to an operator
network only, see the comment on `location ^~ /admin/` in
`infra/gateway/kemudi.prod.conf`.

### Kemudi instance admins

The skill library (Awak's skills, marketplaces) is managed by Kemudi instance
admins, which are separate from Taiga superusers. They are listed by Taiga
user id in `KEMUDI_ADMIN_USER_IDS`:

1. Sign in, then open `https://kemudi.example.com/api/kemudi/me`. The `id`
   field is your Taiga user id.
2. Set `KEMUDI_ADMIN_USER_IDS=<id>[,<id>...]` in `infra/.env`.
3. Apply: `docker compose -f infra/docker-compose.yml --env-file infra/.env up -d`
   (recreates the orchestrator).

`KEMUDI_ADMIN_USERNAMES` exists as a fallback, but a user can rename
themselves to a former admin's username, so prefer ids.

## 6. AI features (optional)

The contract baseline, change-request check and backtests call a model through
`kemudi-hermes`. Set `KEMUDI_AI_BASE_URL`, `KEMUDI_AI_API_KEY` and
`KEMUDI_AI_MODEL`, then start with the `ai` profile:

```sh
docker compose -f infra/docker-compose.yml --env-file infra/.env --profile ai up -d --wait
```

Pass the same `--profile` flags to every later `up`, or set
`COMPOSE_PROFILES=ai` in your shell. Contracts and baselines are stored in the
`kemudi-ai-data` volume ([backup.md](backup.md)); they are confidential and
are sent to the model provider you configure.

## 7. Product research (optional)

"Riset Produk" (a project's Research page) runs four agents: competitor
research, feature suggestions, a project data report and custom research.
They use the model connection of section 6 (`--profile ai`). The feature
suggestions and the data report need nothing else.

Competitor and custom research read the open web through one more service,
`kemudi-riset`. Turn it on with the `riset` profile and its URL:

```sh
# infra/.env
KEMUDI_RISET_URL=http://kemudi-riset:8642/v1
```

```sh
docker compose -f infra/docker-compose.yml --env-file infra/.env --profile ai --profile riset up -d --wait
```

`KEMUDI_RISET_API_KEY` is generated by `scripts/init-secrets.sh` (run it again
after an upgrade: it only fills what is empty). Without the service these two
agents still run, from the model's own knowledge, and the report says so.

What to know before enabling it:

- **It sends searches to third parties.** With no key set, search and page
  reading go through the public free tiers Hermes ships with (Exa, Parallel).
  Set `TAVILY_API_KEY`, `EXA_API_KEY`, `FIRECRAWL_API_KEY`,
  `BRAVE_SEARCH_API_KEY` or `SEARXNG_URL` in `infra/.env` to use your own
  provider or a self-hosted SearXNG.
- **It is given little.** The web agent gets the brief a member typed and a
  short product summary written from the project's README; never the code,
  the backlog or a secret. Tell your team that what they write in a brief is
  used in web searches.
- **It is boxed in.** `kemudi-riset` has web search and page reading only (no
  terminal, no files), and its networks reach the internet and nothing else in
  the stack. Web pages can try to steer a model; the report is the only thing
  that comes back, and it is shown as plain Markdown.
- **It spends model tokens.** A web run takes 2 to 15 minutes of model calls.
  A project can have two runs queued or running at a time.

## 8. Awak (experimental)

Awak is the autonomous dev loop: it picks up user stories, writes code on
branches, runs gates and QA in a sandbox, and pushes `awak/*` branches. It is
**experimental** in 1.0 and off by default. Its services carry the label
`io.kemudi.experimental=true`.

```sh
docker compose -f infra/docker-compose.yml --env-file infra/.env --profile awak up -d --wait
```

The `awak` profile starts `kemudi-hermes`, `kemudi-awak` (the agent),
`kemudi-runner` (runs branch code, installs and Playwright), `kemudi-dind`
(sandboxed Docker for a project's compose services) and `kemudi-svc` (the only
client of that Docker daemon). Then create the Taiga users `awak` and
`awak-qa`, set `KEMUDI_AWAK_PASSWORD`, `KEMUDI_QA_PASSWORD` and
`KEMUDI_AWAK_PROJECTS`, and add repositories by SSH URL in Project settings ->
Agent. (The dev stack's "work on the Kemudi checkout itself" mode needs the
repository's `.git` mounted and is not available in production.)

Understand the risks before enabling it:

- **It runs model-written code.** `kemudi-runner` executes whatever the branch
  contains (package installs, build scripts, tests) and has outbound internet
  through the `kemudi-egress` network. It holds no secrets and runs children as
  an unprivileged uid with dropped capabilities, but treat it as untrusted.
- **`kemudi-dind` is a privileged container** (Docker-in-Docker with user
  namespace remapping). A container escape there is a host compromise. Run
  Awak on a dedicated host or VM if that matters to you.
- **Outbound traffic is not filtered.** There is no egress proxy:
  `kemudi-egress` is an ordinary bridge network. Restrict it with host
  firewall rules if you need an allowlist.
- **It pushes to your repositories** with the deploy keys you give it, and can
  comment on stories. Use deploy keys scoped to one repository, protect your
  main branches, and review `awak/*` branches before merging.
- **It spends model tokens** without a person in the loop. Set budgets with
  your provider.
- The resource caps above (2 + 4 + 5 + 1 GB) are per container; size the host
  accordingly.

## Next

- Smoke-test the install: `sh scripts/smoke-test.sh https://kemudi.example.com
  -f infra/docker-compose.yml --env-file infra/.env` (adds a `smoke-admin`
  superuser; delete it afterwards).
- Schedule backups: [backup.md](backup.md).
- Upgrades: [upgrade.md](upgrade.md).
