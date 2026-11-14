# Awak iteration 3, stage 1: project workspace, runbook, Setup Assistant

Status: design, 2026-11-14. Builds on `2026-11-13-awak-dev-loop-design.md`,
`2026-11-14-awak-project-setup-design.md` and `2026-11-14-awak-byok-design.md`.
The user's request and the stage split are in
`docs/superpowers/plans/2026-11-14-awak-iteration-3-handoff.md`. The user
opted out of a Q&A round; anything not taken from the handoff is the
builder's call and is marked **(call)**.

## Problem

Today the loop only knows how to run Kemudi itself:

- QA always starts `pnpm exec vite` and proxies to Kemudi's gateway with a
  Kemudi QA token. On playfast (Next.js in `frontend/`, Flask + Postgres +
  Redis via `docker compose`) QA failed three times with "dev server did not
  start".
- Command detection reads only the repo root, so playfast got **no gates**.
- Job workspaces are `/workspace/awak-us-<n>`: Kemudi's US #1 and playfast's
  US #1 share a directory.
- Nothing can start a project's backing services (database, cache, API).

## Goals (stage 1)

1. **Project workspace** `/workspace/<slug>/`, with every repo of the project
   side by side in each story's folder.
2. **Runbook per project**: apps (per-repo install, checks, build), services
   (compose or process) with ports and healthchecks, env vars in an
   encrypted per-project vault, optional seed, QA entry point.
3. **Gates and QA driven by the runbook**; the Kemudi project without a
   runbook keeps today's behaviour.
4. **Setup Assistant**: "Configure automatically" in Project settings →
   Agent proposes a runbook, proves it in the runner, asks for missing env
   values, shows logs, a screenshot and RAM/CPU, and saves on approval.
5. **Detection in subfolders** (`frontend/`, `backend/`...).
6. **QA mode per project**: Off, Gates only, Browser.

Non-goals: preview links (stage 2), client VPS execution (stage 3), and
**commits to more than one repo in one story** (see "Multi-repo").

## 1. Workspace layout

```
/workspace/<slug>/
  us-<ref>/<repo-name>/     one folder per story; the story's repo on
                            awak/us-<ref>, the project's other repos at
                            their default branch (read-only context)
  setup/<repo-name>/        the Setup Assistant's checkouts (default branch)
```

- The orchestrator's bare repos (`repos/<id>.git`) stay the single synced
  copy of each repo ("cloned once, kept in sync"): `sync_default` fetches
  them before every story and every setup run.
- **(call) A story checkout is a local clone from the bare repo, not a
  `git worktree`.** Worktrees share one `.git` that the agent could write
  (hooks, config, refs), which would leak from one story into the next and
  into the orchestrator's merges. A local clone hard-links objects, so it
  costs about the same as a worktree, and keeps iteration 1's isolation
  (remote removed, orchestrator only does hardened fetches).
- Runner requests name a workspace by a relative `path`
  (`<slug>/us-<ref>/<repo>` or `<slug>/setup/<repo>`) validated by regex;
  `job` (`awak-us-<n>`) is gone. Slugs are Taiga slugs (`[a-z0-9-]`), repo
  names are validated the same way on save.
- `/workspace/<slug>` stays under `HERMES_WRITE_SAFE_ROOT=/workspace`.

### Multi-repo

**(call) Stage 1 commits to one repo per story** (the role's first repo, as
today). The project's other repos are cloned beside it so the agent can
read contracts and the runbook can start their services; changes there are
not collected and the prompt says so. Committing to several repos needs an
all-or-nothing merge across remotes (push one, the other conflicts → half
merged), which deserves its own design. Playfast is one repo, so stage 1's
target is unaffected.

## 2. Runbook

One JSON document per project (`awak_runbooks`, see Data), validated by a
pydantic model in the orchestrator. Example (playfast):

```json
{
  "apps": [
    {"name": "web", "repo": "pf-web", "dir": "frontend",
     "install": ["pnpm install --frozen-lockfile --ignore-scripts",
                 "pnpm run build:icons"],
     "checks": ["pnpm exec tsc --noEmit", "pnpm lint"],
     "build": [],
     "env": {"INTERNAL_API_URL": "{services.api.url}"}},
    {"name": "api", "repo": "pf-web", "dir": "backend",
     "run_in": "api:backend",
     "checks": ["python -m pytest -q tests"]}
  ],
  "services": [
    {"name": "api", "kind": "compose", "repo": "pf-web",
     "file": "docker-compose.yml",
     "compose_services": ["postgres", "redis", "backend"],
     "expose": "backend:5000", "health": "/api/health",
     "env": ["JWT_SECRET_KEY"]},
    {"name": "web", "kind": "process", "app": "web",
     "command": "pnpm exec next dev --port {port}",
     "health": "/", "ready_timeout": 240}
  ],
  "env": [
    {"name": "JWT_SECRET_KEY", "secret": true, "required": true,
     "description": "any 64-char hex for testing"}
  ],
  "seed": {"service": "api", "command": "python scripts/seed_campaigns.py"},
  "qa": {"service": "web", "env": ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]}
}
```

- **apps**: per repo and subdir. `install` runs before coding; `checks`
  and `build` are the gates. A command is one line, split with `shlex`, no
  shell; argv[0] must be on the runner's allowlist (as today). `run_in:
  "<service>:<compose service>"` runs the app's commands inside that compose
  service's image instead (`docker compose run --rm`), for stacks the runner
  has no toolchain for (playfast's Python backend); argv there is not
  allowlisted because it runs inside the project's own container.
- **services**:
  - `compose`: the repo's compose file, only the listed services, one
    `expose` (`service:port`) reached by the runner; `health` is a path on
    it. Started in a sandboxed Docker daemon (section 4).
  - `process`: a long-running command of an app in the runner (`{port}` is
    allocated by the runner), `health` a path on it.
  - `{services.<name>.url}` placeholders in app/service env resolve to the
    started service's base URL.
- **env**: names, descriptions, `secret` and `required` flags; values live
  only in the vault. A service gets the vault values it lists (`env`), plus
  non-secret defaults. QA's spec gets only the names in `qa.env`.
- **seed**: one command run in a compose service after it is healthy.
- **qa.service**: the service whose URL is QA's `baseURL`.

### Gates with a runbook

Gates run for the story repo's apps whose `dir` contains a changed file;
if no app matches, all apps of that repo. A `run_in` app's commands run in
its compose service. Output, timeouts and the "first gate failed, stop"
rule stay as today.

### Without a runbook

The project's repo rows keep their `subdir` and command fields, and gates
use them as today; QA uses iteration 1's vite + gateway path only when the
repo is the local Kemudi repo (`host_git`). Any other project without an
approved runbook and QA mode Browser is refused at save time and, if
already set, treated as Gates only with a card comment.

## 3. QA mode

`awak_projects.qa_mode`: `off` | `gates` | `browser`.

- `off`: after the commit is collected, no gates and no QA; the card goes
  to Done + `awaiting-merge`.
- `gates`: gates only, then Done + `awaiting-merge`.
- `browser`: gates, then browser QA against the runbook's services (or the
  Kemudi path).
- **(call)** Merge mode `auto` requires `browser` (auto-merging code no one
  and nothing exercised is the one case we refuse). In `off`/`gates` the
  merge re-check runs gates only. Default for new projects: `gates`;
  migration sets `browser` for projects that already have Awak enabled with
  the Kemudi repo, `gates` for the others.

## 4. Running services: sandboxed Docker

- A new **`kemudi-dind`** container (`docker:27-dind`, privileged — Docker
  needs it) listens **only on a unix socket** in a volume shared with one
  other container. Its data dir is its own volume. It is on
  `kemudi-sandbox` (so the runner can reach published ports) and on
  `kemudi-egress` (image pulls, pip/npm in builds).
- A new **`kemudi-svc`** container (the runner image, `RUNNER_ROLE=svc`)
  holds that socket and is the only thing that talks to Docker. It runs the
  compose CLI and never runs branch code itself; the builds run inside
  `kemudi-dind`. Ops: `svc_up`, `svc_exec` (for `run_in` and seed),
  `svc_logs`, `svc_stats`, `svc_down`.
- **Why not the runner?** The runner executes branch code (install scripts,
  tests). If it could reach the Docker daemon, branch code could start a
  privileged container and own the host. The daemon has no TCP listener,
  so nothing on the network can reach it.
- **Compose sanitizer** in `kemudi-svc`, run on `docker compose config
  --format json` of the selected services, refusing the whole file on:
  `privileged`, `cap_add`, `devices`, `device_cgroup_rules`, `security_opt`,
  `pid`/`ipc`/`network_mode`/`userns_mode`/`uts`/`cgroup` other than
  default, `cgroup_parent`, bind mounts (only named volumes and tmpfs),
  `volumes_from`, `build.context`/`dockerfile`/`env_file`/`secrets`/
  `configs` paths outside the repo checkout, `build.network: host`,
  `extra_hosts`, `sysctls`, `runtime`, `isolation`. It writes its own
  normalized compose file: `restart: "no"`, `mem_limit` capped (default
  2 GB per service, 6 GB per project), `pids_limit` 512, the exposed port
  published on `0.0.0.0` with a random host port, every other `ports`
  removed. The compose project name is `<slug>-us<ref>` (or `-setup`).
- Vault values reach compose through an env file in a private temp dir in
  `kemudi-svc`, deleted after `up`. They end up in the project's own
  containers, which is where an app's secrets belong.
- Every QA run (and setup proof) ends with `svc_down -v`; a sweep on worker
  start removes compose projects of jobs that are not running.

## 5. QA with a runbook

1. `svc_up` the compose services (build cached in dind), wait for health,
   run `seed`.
2. Runner op `qa` (extended): starts the `process` services in the story
   checkout with their resolved env, waits for health, runs the spec twice
   with `QA_BASE_URL` = `qa.service` URL and the `qa.env` vault values as
   process env, stops the processes.
3. `svc_down`.

The QA agent's task lists the base URL, the env var names it may read
(`process.env.X`) and the app dirs; never a value. Kemudi's path (token in
localStorage) is unchanged. Service start failure is an infra error with
the service logs (redacted) in the event.

## 6. Setup Assistant

A **setup run** (`awak_setup_runs`) is processed by the worker after
requested merges, so it shares the lease and the runner. Setup steps and
stories take turns: a step runs when the last tick did not run one, or when
no story is ready, so one project's setup never holds every project's
stories. An environment problem sets `not_before` (10 s × failures) instead
of sleeping in the tick. One active run per project is a partial unique
index on `project_slug`.

States: `queued → reading → proving → needs_input → proving → ready →
approved | failed | cancelled | superseded` (a `ready` run is superseded
when a newer run starts or another is approved; it can't be approved).

1. **Clone**: sync every repo, check out the default branch to
   `/workspace/<slug>/setup/<repo>/`.
2. **Detect** (no model): subfolder detection (section 7) gives a draft.
3. **Propose**: the setup agent (Hermes, template `setup`, the project's
   model) reads `package.json`, lockfiles, `docker-compose.yml`,
   `Dockerfile`, README and `.env.example` in the setup checkout and writes
   `/workspace/<slug>/setup/runbook.json`. Prompt: the schema, the
   allowlist, the draft, the rules (no secrets in the runbook, prefer the
   project's compose for backing services, dev servers over production
   builds for QA).
4. **Validate** with the pydantic model; errors go back to the agent (max 2).
5. **Missing env**: `required` names without a vault value → state
   `needs_input`; the UI shows a form (name, description, secret). Values
   go to the vault; the run continues.
   **Confirm saved env**: the agent picks which vault names its runbook
   wires (compose `env`, `init`/`seed` `env`, `qa.env`, `qa.login`), so
   before a proof uses a saved value not typed in this run, the run stops in
   `needs_input` with `confirm_env: [{name, secret, used_in}]`; an admin
   confirms (`POST /setup/{id}/env` with `confirm: true`), the names go to
   `confirmed_env`. The proof gets only the wired values.
6. **Prove** in the runner/svc: install every app, run its checks once
   (failures reported, not blocking: an existing red test is the project's
   state, not a broken runbook), `svc_up`, seed, start processes, health,
   one Playwright screenshot of `qa.service` `/`, `svc_stats` + process RSS
   for RAM/CPU, logs tail of each service, then `svc_down`.
7. **Fix loop**: a failed install, start or health goes back to the agent
   with the redacted logs ("fix the runbook"), max 3 rounds; then `failed`
   with the last logs.
8. **Ready**: the UI shows the runbook, per-step results, logs, the
   screenshot and peak RAM/CPU. **Approve** saves it as the project's
   runbook (version +1, approver, time) and offers QA mode Browser.

The screenshot is served by an authenticated endpoint; logs are redacted
with the vault values and the usual secrets before they are stored.

## 7. Detection in subfolders

`detect_apps(tree, paths)`: looks at the repo root and every first-level
directory (skipping `node_modules`, `.git`, dot dirs, `docs`) for
`package.json`, `pyproject.toml`, `requirements.txt`, `go.mod`,
`Cargo.toml`, `Makefile`, `docker-compose.yml`/`compose.yaml`. Returns
apps `{dir, kind, commands}` and compose files. The existing repo "detect"
fills `subdir` + commands from the first app when the root has none
(playfast → `frontend/`). The Setup Assistant gets the full list.
`requirements.txt` → `run_in` suggestion when a compose service builds that
dir.

## Data

- `awak_projects.qa_mode` (str, default `gates`).
- `awak_runbooks`: `project_slug` PK, `spec` JSON, `version`,
  `approved_by`, `approved_at`, `updated_at`.
- `awak_env_vars`: `id`, `project_slug`, `name` (`[A-Z_][A-Z0-9_]*`),
  `value_enc` (Fernet, `crypto.py`), `secret` bool, `updated_by`,
  `updated_at`; unique (slug, name). The API returns non-secret values in
  full and never a secret's value (only `set: true`).
- `awak_setup_runs`: `id`, `project_slug`, `state`, `proposal` JSON,
  `steps` JSON (name, ok, output tail), `missing_env` JSON, `screenshot`
  path, `resources` JSON, `error`, `cost_idr`, `created_by`, timestamps.

## API (under `/api/ai/v1/projects/{slug}/agent`)

- `GET/PUT /runbook` (admin PUT; validated; bumps version).
- `GET /env` (names, flags, non-secret values), `PUT /env/{name}`,
  `DELETE /env/{name}` (admin).
- `POST /setup` (admin; one active run per project), `GET /setup/latest`,
  `POST /setup/{id}/env` (`{values, confirm}`: fill missing values and/or
  confirm the listed saved ones, then resume),
  `POST /setup/{id}/approve`, `POST /setup/{id}/cancel`,
  `GET /setup/{id}/screenshot`.
- `PUT /settings` accepts `qa_mode`.
- `POST /repos/{id}/detect` returns the subfolder apps.

## Web (Project settings → Agent)

- **QA mode** segmented control in the merge policy card.
- **Runbook** card: summary (apps, services, env names, version, approver),
  "Configure automatically", "Edit JSON" (advanced).
- **Setup Assistant** panel: step timeline, live state (polling), missing
  env form, logs per service, screenshot, RAM/CPU, Approve / Cancel.
- **Env & secrets** card: list, add/edit (secret values write-only).
- en + id strings in the `agent` namespace; built with `impeccable`.

## Security summary

- Branch code never reaches the Docker daemon (socket only in `kemudi-svc`).
- Compose files are sanitized before use; no bind mounts, no privileges.
- Vault values: encrypted at rest, never in prompts, redacted from every
  comment, event, log, setup step and agent feedback, scanned for in diffs.
- Runner paths are validated relative paths under `/workspace`.
- Setup runs are admin-only; approval is a human click.

## Testing

- Orchestrator unit tests: runbook model, gates app selection, QA mode
  routing, setup state machine with fake agent/runner/svc, vault redaction,
  workspace paths, detection in subfolders.
- Runner tests: path validation, sanitizer accept/reject table, process
  service start/health/stop.
- Web tests for the new cards.
- **Live on playfast**: run Configure automatically, fill env, approve,
  set QA mode Browser, unblock #1 and #3, watch both reach Done.

## Panel review (delivery, security, QA/devops) and what changed

The three reviews agreed the design is right but too big for one PR, and
that the Docker part needs a stricter boundary. Resolutions:

### Delivery: three PRs, each live-tested and merged

- **1a**: workspace paths and the runner `path` contract (all call sites in
  `worker.py` and `merge.py` at once, via one `runner_path()` helper),
  subfolder detection, `qa_mode`, runbook model + `GET/PUT /runbook` + Edit
  JSON, gates from the runbook shared by worker and merge (`checks.py`),
  `process` services in runner QA. Live: playfast #1 in `gates` mode,
  Kemudi regression on the vite path.
- **1b**: vault, `kemudi-dind` + `kemudi-svc`, sanitizer, compose services,
  `init`/`seed`, `run_in`, `qa.login`, QA against compose. Live: #1 in
  `browser`, #3 gates via `run_in`.
- **1c**: Setup Assistant (backend, then UI). Live: Configure
  automatically on playfast.

Further decisions:
- `qa_mode` migration: `browser` if any repo of the project is `host_git`,
  else `gates`; a project in `auto` that lands in `gates` is downgraded to
  `approve` (event logged).
- `off`/`gates`: no acceptance-criteria requirement, no evidence upload,
  no spec saved, own Done wording; the clean check (workspace == commit)
  runs after gates so Done is tied to the merged sha. Merge re-check runs
  the same gate selection; QA re-run only in `browser`.
- Old `/workspace/awak-us-*` folders are deleted once at worker start when
  no job is running (they were shared between projects; untrusted). Blocked
  playfast #1 re-runs its coding step; its branch survives in the bare repo.
- The story's sibling repos are listed in the coding task; changes to them
  are discarded. Folder names use the repo name pinned on the job.
- A changed file at the repo root (outside every app dir) selects all apps.
- Setup runs advance one step per tick and persist state; `needs_input`
  holds nothing; cancel brings services down first.

### Security

- `kemudi-svc` has its **own key**, sits on a network only the
  orchestrator reaches (`kemudi-svcnet`, internal), and mounts `/workspace`
  **read-only**. The dind socket lives on an svc-only volume.
- `kemudi-dind` is **not** on `kemudi-sandbox`: it has its own internal
  network shared with the runner (for published ports) plus egress. It runs
  with `--userns-remap=default`, `mem_limit`, `pids_limit`, a fixed
  `--default-address-pool`.
- The runner server runs as root with only `SETUID`/`SETGID`; every child
  (branch code) runs as uid 10000 with a **clean environment** (no runner
  key), so `/proc/1/environ` and the key are out of reach.
- Sanitizer is an **allowlist**: compose is read with `--no-interpolate`
  (so `:?` in unselected services and svc's own env never matter), reduced
  to the selected services plus their `depends_on` closure, then
  interpolated with a cleared environment and only the vault env file.
  Service keys allowed: `image`, `build.{context,dockerfile,args,target}`,
  `command`, `entrypoint`, `environment`, `healthcheck`, `depends_on`,
  `working_dir`, `user`, named `volumes`, `tmpfs`, `expose`, `ports`
  (rewritten). Everything else, `include`, `extends`, top-level
  `secrets`/`configs`, and volume `driver`/`driver_opts`/`external`/`name`
  are refused; top-level `networks` are dropped. Paths must resolve (no
  symlinks) inside the checkout. Built services get `image:
  kemudi-<project>-<svc>` so one project cannot shadow another's tags;
  `--pull always` for the rest.
- Images of all projects share one dind image store. `svc_down` removes the
  project's built images (label `kemudi.project`), so with one job at a time
  no other project's image is there to use; BuildKit's cache stays. As a
  second line, after interpolation the same checks run again (an
  `image: "${UNSET:-kemudi-...}"` or a folder named `${X:-..}` shows what it
  is only then): non-built images starting with `kemudi-` or `sha256:` (or a
  bare image id) are refused, and each Dockerfile is scanned for `FROM`,
  `--from=`, `from=` and `# syntax=` naming such an image, also through an
  `ARG` default or build arg. The Dockerfile scan is simple, not a parser.
- Known limit: `spec_env` (and `qa.login`) values reach branch code: the QA
  specs and the app under test read them. QA values must be test-only
  accounts and keys; the UI's Env card already says "test/dev values only".
- Runbook env names may not start with `KEMUDI_`, `DOCKER_`, `COMPOSE_`,
  `GIT_`, nor be `PATH`, `LD_PRELOAD`, `LD_LIBRARY_PATH`, `NODE_OPTIONS`,
  `PYTHONPATH`, `HOME`. `dir`/`file`/`repo` are relative and inside the
  project's repos. The runbook is used only from the DB copy.
- Vault: Fernet key derived with HKDF from `KEMUDI_SECRET_KEY` (context
  `awak-vault`); values of any length redacted plus base64/URL-encoded
  variants; UI labels it "test/dev values only".
- Accepted for stage 1, stated here: one dind for all projects (per-project
  daemons are stage 3 territory with the client VPS); Hermes' write root is
  all of `/workspace` (one job runs at a time).

### QA/devops

- Runbook gets `init` (one-shot `run_in` commands after backing services are
  healthy and before the API's health wait: playfast needs `create_all` and
  an admin user from vault values) and `qa.login` (a form login the runner
  performs once with Playwright, saving `storageState`; specs start logged
  in). QA's base URL uses `localhost`, so secure cookies work over http.
- The interpolated compose file stays (0600, svc tmpfs) for the life of
  the compose project; `down -v` and the sweep work by project name.
- `run_in` gates rebuild the image from the story checkout first; setup
  separates "checks could not run" from "red tests".
- Process services log to `<checkout>/.qa/logs/<name>.log`; failed starts
  return the redacted tail. Health needs 2xx/3xx. After health, the runner
  warms up the paths listed in `.qa/routes.txt` (written by the QA agent).
  Spec runs share one database: the QA prompt says so.
- Runner gets `npm_config_store_dir=/pnpm-store`,
  `NEXT_TELEMETRY_DISABLED=1`, `NODE_OPTIONS=--max-old-space-size=2048`
  for process services, and `mem_limit` 4g. Each op has a deadline below
  the client's wait; `svc_up` has one 1400 s budget its build (cold 15 min,
  one retry), start and port steps share (the client waits 1500 s), and
  svc_down/svc_exec wait (bounded) for an in-flight `svc_up` of the same
  project. Processes die by process group; the worker's start sweep kills
  leftovers, and when idle the worker sweeps compose projects at most every
  10 minutes (keeping running jobs and merges).
- Resources: sample every 2 s during the proof (dind `docker stats`, runner
  cgroup `memory.peak`), report peak MB and CPU-seconds, cold or warm.
