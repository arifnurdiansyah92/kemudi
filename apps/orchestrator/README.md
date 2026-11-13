# apps/orchestrator

Kemudi AI service. It turns a contract (SOW/SPK, PDF or DOCX) into a
baseline a PM approves. It then classifies requests against that baseline as
in baseline, Change Request candidates, or needing clarification, and replays
past requests to measure how well the classification holds up. See
`docs/superpowers/specs/2026-11-11-contract-baseline-cr-design.md`.

- **Model calls.** Every call goes through Hermes (`services/awak`, service
  `kemudi-hermes`) and is logged in `ai_calls`. PM decisions are logged in
  `decisions`. Both tables are append-only.
- **API.** The web UI reaches it at `/api/kemudi/*`. The gateway strips that
  prefix before passing requests on. Callers send their Kemudi token; project
  admins can change things, and members can only read.
- **Data.** Data lives in `data/` (SQLite and uploaded contracts). The folder
  is gitignored because contracts are confidential.

## Develop

```sh
cd apps/orchestrator
uv sync
uv run pytest
```

## CLI

```sh
uv run python -m kemudi_ai extract data/pilot/contract.pdf
uv run python -m kemudi_ai baseline <project-slug> data/pilot/contract.pdf --rate-card data/pilot/backtest.json
uv run python -m kemudi_ai approve <project-slug> --by "PM name"
uv run python -m kemudi_ai backtest <project-slug> data/pilot/backtest.json
```

## Configuration

These come from the environment, normally `infra/.env`:

| Variable | Default |
| --- | --- |
| `KEMUDI_HERMES_URL` | `http://localhost:8642/v1` |
| `KEMUDI_HERMES_API_KEY` | (none) |
| `KEMUDI_AI_MODEL` | `deepseek-flash` |
| `KEMUDI_AI_DB_URL` | `sqlite:///data/kemudi-ai.db` |
| `KEMUDI_TAIGA_API_URL` | `http://localhost:9100/api/v1` |

## Awak dev loop

Iteration 1 of the loop in
[the design](../../docs/superpowers/specs/2026-11-13-awak-dev-loop-design.md):
a request becomes stories; Awak (Hermes) codes each one on an `awak/us-<n>`
branch; the runner checks it (`tsc -b`, eslint, vitest, `vite build`) and runs
a Playwright spec written by a QA agent, twice, with a screenshot per
acceptance criterion; the card moves to Done (tagged `awaiting-merge`) or back
to In progress with the failures, up to 3 attempts.

Done means QA passed, not merged: review the branch yourself
(`git log main..awak/us-<n>`, `git diff main...awak/us-<n>`) and merge it.

### Run it

1. Fill the Awak block in `infra/.env` (see `infra/.env.example`).
2. Start the stack with the profile:
   ```sh
   docker compose -f infra/docker-compose.dev.yml --env-file infra/.env --profile awak up -d --build
   ```
3. Create the bot users and projects (idempotent):
   ```sh
   docker compose -f infra/docker-compose.dev.yml --env-file infra/.env exec -T \
     -e KEMUDI_AWAK_PASSWORD -e KEMUDI_QA_PASSWORD -e AWAK_PM=webdev \
     kemudi-back python manage.py shell < infra/awak/bootstrap.py
   ```
   (Export the two passwords from `infra/.env` into your shell first.)
4. Add work, either way:
   - `POST /api/kemudi/projects/kemudi/intake` with form field `text` (or a
     PDF/DOCX `file`), as a project admin; or
   - in the board: a story in **Ready** with the tag `agent-ready` and an
     `## Acceptance criteria` list in its description.

The worker polls every 20 s and takes one story at a time. To stop Awak on a
story, remove the tag, block the card or move it; to send a Done story back,
move it to In progress and write what is wrong in a comment.

### Configuration

| Variable | Default | |
| --- | --- | --- |
| `KEMUDI_AWAK_PROJECTS` | (empty: worker off) | project slugs, comma-separated |
| `KEMUDI_AWAK_PASSWORD`, `KEMUDI_QA_PASSWORD` | | Taiga users `awak`, `awak-qa` |
| `KEMUDI_AWAK_API_KEY`, `KEMUDI_RUNNER_KEY` | | guard kemudi-awak / kemudi-runner ports |
| `KEMUDI_AWAK_MODEL`, `KEMUDI_QA_MODEL` | `deepseek-flash` | |
| `KEMUDI_MAX_ATTEMPTS` | `3` | |

### Boundaries

- kemudi-awak runs on an internal network only and holds no secrets; the
  model key is added by kemudi-llm-proxy. kemudi-runner also holds no
  secrets but can reach the internet (for npm); the QA token it gets per run
  belongs to `awak-qa`, a member of the QA sandbox project only.
- Only `awak/us-<n>` branches are pushed, and only into the local repo's git
  data (`.git`, mounted into the orchestrator). Nothing goes to GitHub.
- Diffs and comments are scanned for secrets before they leave the sandbox.
- The worker refuses any Taiga that is not the local dev stack.

## Project setup (iteration 2)

Per-project Awak settings live in the orchestrator DB (`awak_projects`,
`awak_repos`, `awak_roles`, `awak_keys`); `KEMUDI_AWAK_PROJECTS` only seeds
them once. See
[the design](../../docs/superpowers/specs/2026-11-14-awak-project-setup-design.md).

**Agent settings API** under `/api/kemudi/projects/{slug}/agent/`. Reads
need project membership, writes need project admin, and every write is a
`decisions` row without secrets.

- `GET/PUT settings`: on/off, merge mode, deploy command, executor
  (`local` or `ssh` with host, port, user), last preflight.
- `GET/POST repos`, `PUT/DELETE repos/{id}`, `POST repos/{id}/key` (a
  Kemudi-generated deploy key; only the public key is returned),
  `POST repos/{id}/check` (clone, push dry-run, detected commands).
- `GET/POST roles`, `PUT roles/{id}`, `GET roles/{id}/prompt` (the fixed
  Kemudi rules, role template and project overlay).
- `POST machine/key`, `POST machine/check` (CPU, RAM, disk and Docker
  against 4 vCPU / 8 GB / 40 GB per job, and job slots),
  `DELETE machine/host-key`. Jobs still run on `local` until remote
  execution ships; the SSH machine is only checked and used for deploys.
- `GET jobs`, `GET stories/{id}`, `POST stories/{id}/merge`.

Intake for the UI is `POST /projects/{slug}/intake/draft` (drafts, creates
nothing) then `POST /projects/{slug}/intake/create` (as the caller, so
Taiga's permissions apply; the server decides Ready, the PM can only hold a
story in New).

**Merge modes.** `manual`: QA passed means Done plus `awaiting-merge`, a
human merges (iteration 1). `approve` (the default): an admin clicks Merge
and Kemudi merges into the default branch and pushes. `auto`: Kemudi merges
and pushes as soon as QA passes. A merge that is not a fast-forward of the
QA'd commit runs the gates again (and in `auto` the QA spec too) before the
push; the push is never forced. The optional deploy command runs after a
merge, over SSH or in the runner sandbox.

**`KEMUDI_SECRET_KEY`** is a Fernet key that encrypts the generated private
keys at rest. Without a valid one, every endpoint that makes or uses a key
answers 503; nothing falls back to plaintext. Generate one with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
and keep it: losing it makes stored keys unusable (generate new ones).
