# Kemudi

Kemudi is an open-source project management platform built on the
[Taiga](https://taiga.io) backend, with a new web UI and an AI agent ("Awak")
that works alongside the team.

> Status: early. The backend runs, and the new web UI covers sign-in,
> projects, backlog, kanban and story detail. The AI service is not written
> yet. See [Roadmap](#roadmap).

## Repository layout

```
kemudi/
├── apps/
│   ├── web/              # new UI (React, shadcn/ui), see apps/web/README.md
│   └── orchestrator/     # Kemudi AI service: webhooks, queue, audit log — not started
├── services/
│   ├── kemudi-back/      # fork of taiga-back 6.10.2 (MPL-2.0), git subtree
│   ├── kemudi-events/    # fork of taiga-events 6.10.0 (MPL-2.0), git subtree
│   └── awak/             # fork of NousResearch/hermes-agent (MIT), git submodule
├── infra/
│   ├── docker-compose.dev.yml
│   ├── gateway/          # nginx config for the dev stack
│   └── sandbox/          # image Awak runs code in — not started
├── docs/                 # ADRs, architecture, third-party licenses
└── LICENSES/             # AGPL-3.0, MPL-2.0, MIT
```

## Quick start (development)

Requirements: Docker with Compose v2, Git.

```sh
git clone --recurse-submodules https://github.com/arifnurdiansyah92/kemudi.git
cd kemudi
cp infra/.env.example infra/.env
docker compose -f infra/docker-compose.dev.yml --env-file infra/.env up -d --build
docker compose -f infra/docker-compose.dev.yml --env-file infra/.env exec kemudi-back \
    python manage.py createsuperuser
```

Open <http://localhost:9100> for the Kemudi UI. Screens it does not have yet
are on the stock `taigaio/taiga-front` at <http://localhost:9101>, which uses
the same backend and accounts.

To work on the UI with hot reload, run `pnpm dev` in `apps/web` (Node 22.12+)
and open <http://localhost:5173>. See [apps/web/README.md](apps/web/README.md).

If you cloned without `--recurse-submodules`: `git submodule update --init --depth 1`.

## Working with the forks

`kemudi-back` and `kemudi-events` are git subtrees, so their full upstream
history lives in this repo and upstream releases can be merged in:

```sh
git remote add taiga-back https://github.com/taigaio/taiga-back.git
git fetch --no-tags taiga-back tag 6.11.0
git subtree merge --prefix=services/kemudi-back 6.11.0 --squash
```

Keep changes to `kemudi-back` small and isolated so these merges stay easy.
See [docs/adr/0001-monorepo-and-forks.md](docs/adr/0001-monorepo-and-forks.md).

`awak` is a submodule pointing at
[arifnurdiansyah92/hermes-agent](https://github.com/arifnurdiansyah92/hermes-agent)
because upstream is ~1.4 GB. Make Awak changes in that fork, then bump the
submodule here.

## Roadmap

1. **Monorepo and forks**: done.
2. **`apps/web`**: new UI based on [shadcn-admin](https://github.com/satnaing/shadcn-admin).
   In progress: sign-in, projects, backlog, kanban and story detail are done.
   Next: sprint taskboard, issues, then the taiga-v2 patches.
3. **Kemudi AI**: `apps/orchestrator`, Awak and `infra/sandbox`.

## License

Code written for Kemudi (everything outside `services/`) is licensed under
**AGPL-3.0-or-later**. Forked components keep their own licenses:

| Component | Upstream | License |
|---|---|---|
| services/kemudi-back | taigaio/taiga-back | MPL-2.0 |
| services/kemudi-events | taigaio/taiga-events | MPL-2.0 |
| services/awak | NousResearch/hermes-agent | MIT |

See [NOTICE](NOTICE) and [LICENSES/](LICENSES/).
