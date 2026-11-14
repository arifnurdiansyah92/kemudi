# Handoff: Awak iteration 3 (project workspace, runbook, Setup Assistant)

Written 2026-11-14 so a fresh session can continue on autopilot. Read this
first, then the specs it links.

## What the user asked for

> "idealnya satu project dibuatkan satu folder, isinya repo-repo yg project
> itu... lalu kita kasih agar repo itu bisa di running di server kita atau
> server mereka... dan di project setting ada AI untuk bantu auto configure
> cara running dsbnya"
>
> "buatkan autopilot itu dan coba di playfast"

**Stage 1 is the target now.** Stages 2 and 3 come later, each merged on its
own.

1. **Project workspace.** `/workspace/<slug>/` holds every repo of the
   project side by side. Repos are cloned once and kept in sync, and each
   story gets its own `git worktree`. A story can touch several repos (the
   Fullstack role exists already).
2. **Runbook per project.** It lists:
   - services, such as a backend via the project's `docker compose` and a
     frontend via `pnpm dev`, with their ports;
   - healthcheck URLs;
   - per-repo install, lint/typecheck, test and build commands;
   - env vars and secrets, held in a per-project encrypted vault that never
     reaches prompts;
   - an optional seed command.

   Gates and QA use the runbook instead of today's Kemudi-only assumptions:
   the runner currently always runs `pnpm exec vite` and proxies to Kemudi's
   gateway.
3. **Setup Assistant.** It is the "Configure automatically" button in Project
   settings → Agent. It:
   - clones the repos;
   - has a setup agent read `package.json`, `docker-compose.yml`,
     `Dockerfile`, README and `.env.example`;
   - proposes a runbook, then **proves it** in the runner (install, build,
     start, healthcheck), reading the logs and fixing it until it is green;
   - asks the human for missing env values in a form;
   - shows logs plus a screenshot of the running app, and saves the runbook
     on approval;
   - measures the project's RAM and CPU.
4. **Detection in subfolders.** A repo whose app sits in `frontend/` must get
   that subdir and its commands. Today detection reads only the repo root,
   so playfast had **no gates at all**.
5. **QA mode per project:** Off, Gates only, or Browser. Browser needs the
   runbook to start the app.

- **Later, stage 2:** a preview link per story on the card, with automatic
  cleanup.
- **Later, stage 3:** executing on the client's VPS over SSH. Kemudi
  installs the runner and Awak pair there and talks to it through an SSH
  tunnel. Today the SSH machine only supports preflight and deploy.

## Process the user expects (autopilot)

1. Write a design in `docs/superpowers/specs/`.
2. Run a three-expert panel review: delivery, security, QA/devops.
3. Write a plan in `docs/superpowers/plans/`.
4. Hand the tasks to implementer subagents (backend first, then UI). UI
   work must use the `impeccable:impeccable` skill.
5. Verify each result yourself: run the tests and rebuild the stack.
6. Test live on playfast.
7. Have an independent reviewer subagent review the branch, and fix what it
   finds.
8. Push, open the PR, wait for CI, merge, and delete the branch.

Report in Indonesian, briefly, with what was verified live. Ask questions in
plain chat, never with the question tool. The user said "clear context then
start", so do not re-ask what is decided here.

## State on main (merged: PRs #4–#15)

- **Orchestrator:** `apps/orchestrator/kemudi_ai/awak/`.
  - Core: `worker.py` (state machine, worker lease, per-project isolation),
    `gitops.py` (hardened git, `Repo`), `agent_api.py` (all agent endpoints).
  - Config and keys: `config_store.py`, `llm_conn.py` + `llm_proxy.py`
    (BYOK; the orchestrator is the model proxy), `bot_access.py`.
  - Merging and machines: `merge.py` (manual/approve/auto plus deploy),
    `machine.py` (preflight), `detect.py` (command detection, root only).
  - Agent behaviour: `prompts.py` (layered prompts; templates frontend,
    backend, fullstack, qa), `intake.py`, `verdict.py`.
  - Tests: 179 pass with `cd apps/orchestrator && uv run pytest -q`.
- **Runner:** `infra/runner/runner.py`, a stdlib HTTP service with allowlisted
  operations: install, commit, gates, qa_reset, qa, clean_check and deploy.
  The QA op is hard-wired to vite plus `KEMUDI_DEV_GATEWAY`; this is what
  stage 1 replaces.
- **Web:** `apps/web/src/features/agent-settings/*`, `features/intake/*`,
  `features/item/merge-action.tsx`, `lib/kemudi-ai/agent.ts`, and the `agent`
  i18n namespace (en and id). Web tests: 165 pass.
- **Specs, in order:**
  - `2026-11-13-awak-dev-loop-design.md`
  - `2026-11-14-awak-project-setup-design.md`
  - `2026-11-14-awak-byok-design.md`
- **Results:** `docs/poc/2026-11-awak-loop-iteration-1.md`.

## Running the stack

- **Start:** `docker compose -f infra/docker-compose.dev.yml --env-file
  infra/.env --profile awak up -d`.
- **Rebuild:** run `... build kemudi-orchestrator kemudi-runner kemudi-web`,
  then `up -d` on those same services.
- **Restart only when no job is running** (check `awak_jobs` in
  `/var/lib/kemudi-ai/kemudi-ai.db` inside the orchestrator). A restart cuts
  the live run, which retries as an infra error.
- **Login:** UI at http://localhost:9100 as `webdev` / `webdev123`.
- **Live UI checks:** write a Playwright script, then run it inside the
  runner: `docker cp` it in, then `docker exec kemudi-dev-kemudi-runner-1 sh
  -c 'cd /tmp && NODE_PATH=$(npm root -g) node x.cjs'`. Inside, set
  `BASE=http://kemudi-gateway` and seed localStorage `kemudi.auth`
  (`{token, refresh, user}`) from `POST /api/v1/auth`.
  `scratchpad/shots.cjs` is an example.
- **`infra/.env` is gitignored and holds real secrets.** Never print it or
  commit it. Read values only through `set -a; . infra/.env`.
- **Memory:** Docker only sees 16 GB of the laptop's 32 GB, because WSL2
  defaults to half. A `.wslconfig` with `memory=24GB` was suggested but not
  applied; ask before changing it. Non-Kemudi containers are stopped.

## Playfast, the test project for stage 1

- **Taiga:** slug `playfast`, id 13, Kanban. Awak is enabled in merge mode
  `approve`; the bot user `awak` is now a member.
- **Repo:**
  - repo row `pf-web`, URL `git@github.com:arifnurdiansyah92/playfast.git`;
  - default branch `master`; deploy key in place; access check passes;
  - subdir and all commands are **empty**.
- **Layout:**
  - `frontend/`: Next.js with pnpm (`package.json`, `pnpm-lock.yaml`,
    `next.config.ts`, a Dockerfile);
  - `backend/`;
  - also at the root: `docker-compose.yml`, `nginx/`, `deploy.sh`.
- **Model and roles:**
  - The model is BYOK at project level: `http://host.docker.internal:20128/v1`,
    model `cc/claude-opus-5-5`, a local provider on the user's machine.
  - Roles: PF-FE (web), PF-BE (backend, model `cc/claude-fable-5-1`) and
    PF-QA. There is no Fullstack role yet.
- **Stories:**
  - **#1** (layout /admin/marketing, area-web) is **blocked**. Awak committed
    `d4e3eea5` on `awak/us-1`, but gates were empty and QA failed three times
    with "dev server did not start".
  - **#3** (recommendation endpoint, area-backend) is **blocked**. It hit
    Hermes 409, which is fixed in PR #15, and has not been re-run.
  - **#2 and #4** (area-both) sit in New and need a Fullstack role.
  - Unblock and re-run #1 and #3 once stage 1 ships.

## Lessons learned (do not repeat)

- **Hermes picks the model.** Its API server sends its configured default
  model upstream and ignores the request's `model`. The orchestrator proxy
  maps calls to the single active run alias, and each run sends
  `X-Hermes-Session-Id` set to that alias. Without the header, a retry hits
  409 "session active".
- **Hermes file tools write only under `HERMES_WRITE_SAFE_ROOT`.** It is set
  to `/workspace:/opt/data` in compose. A new workspace path must stay under
  it.
- **GitGuardian scans every commit in a PR,** and so far it has flagged
  only false positives:
  - multi-assignments touching `api_key`;
  - a literal fake password next to a username in tests.

  Build fake credentials at runtime and avoid `password="..."` literals. If
  one is flagged, amend or squash the branch and force-push the branch (never
  main).
- **Bash Python heredocs and printf mangle escapes** such as `\n` and
  `\x89` in this Git Bash. Write files with the Write/Edit tools.
- **The axios client defaults to JSON.** FormData uploads need
  `headers: {'Content-Type': 'multipart/form-data'}`.
- **After a web container rebuild,** the first Playwright load can still use
  the old bundle. Re-run the check before concluding a bug.
- **Verify live, not just in tests.** Every live run so far found a bug the
  tests missed.
