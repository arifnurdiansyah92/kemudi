# Plan: Awak stage 1a (workspace, detection, QA mode, runbook gates, process QA)

Design: `docs/superpowers/specs/2026-11-14-awak-workspace-runbook-design.md`
(read the "Panel review" section last; it overrides earlier sections).
Branch `feat/awak-workspace-runbook`. Stages 1b (vault, dind/svc, compose,
login) and 1c (Setup Assistant) get their own plans.

Tests: `cd apps/orchestrator && uv run pytest -q` (179 pass on main),
`python -m pytest infra/runner/test_runner.py -q`, web `pnpm test` in
apps/web (Node 22 via fnm, see memory). Commit after each task.

## Task 1: workspace paths and the runner `path` contract

- `gitops.Repo` gets `root` (the story's folder) instead of deriving the
  folder from the branch: `Repo.job_dir(branch)` returns
  `<workspace>/<slug>/us-<ref>/<repo-name>` (ref from the branch
  `awak/us-<ref>`). Constructor takes `slug` and `name`; `repo_for()` passes
  them (`config.slug`, the repo row name). Keep the injected-repo path
  working for tests.
- New helper `runner_path(workdir) -> str`: the path relative to
  `settings.workspace_dir`; every `self._runner(...)`/`runner.call(...)` in
  `worker.py` and `merge.py` sends `path=` instead of `job=workdir.name`.
- `infra/runner/runner.py`: `job_dir(body)` reads `path`, validated by
  `^[a-z0-9][a-z0-9-]{0,99}/(us-\d+|setup)/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$`,
  resolved, must stay under WORKSPACE and be a dir (not a symlink). Drop
  `job`/`JOB_RE`.
- Repo names: `agent_api` validates on create/update with
  `^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$` (existing `kemudi`, `pf-web` pass).
- Sibling repos: `prepare` for a story also clones the project's other
  repos (default branch, remote removed, chowned) into the same story
  folder; `code_task` gets `siblings: list[str]` and says they are
  read-only context whose changes are discarded. Failures cloning a
  sibling are infra errors.
- Worker start (`recover`): if no job is `running`, delete
  `<workspace>/awak-us-*` folders once.
- Tests: update all existing tests for the new paths; add path validation
  tests in `infra/runner/test_runner.py`; a test that two projects' US #1
  get different folders.

## Task 2: detection in subfolders

- `detect.py`: `detect_apps(tree, list_dir)` scans the root and first-level
  dirs (skip dot dirs, `node_modules`, `docs`, `.github`) and returns
  `[{dir, kind, commands}]` plus `compose_files`. Node: Next.js
  (`next` in deps) → typecheck `tsc --noEmit` (not `tsc -b`); lint via the
  `lint` script when present (`pnpm lint`) else `eslint .`; pnpm install
  gets `--store-dir /pnpm-store`. Python: `requirements.txt` or
  `pyproject.toml`. Keep `detect_commands` for the root (used today).
- `check_repo` (agent_api): when the root has no app, fill `subdir` and the
  empty command fields from the first detected app; return `apps` in the
  response. A tree listing helper in gitops (`ls-tree` on the bare repo's
  default branch).
- Tests with a fake tree shaped like playfast (`frontend/` Next + pnpm,
  `backend/` requirements, root compose).

## Task 3: QA mode

- `AwakProject.qa_mode` (String(10), default `gates`) in `store.py` (the
  table is already in `_MIGRATED_TABLES`). After `_migrate`, a one-time
  fix-up: projects where any repo url == `settings.host_git` get
  `browser`; a project with `merge_mode == "auto"` and `qa_mode != browser`
  becomes `approve`. Do the fix-up only for rows whose column was just
  added (track it so it does not re-run on every start).
- `config_store`: `qa_mode` in DEFAULTS/SETTING_FIELDS/ProjectConfig.
- `PUT /settings`: accepts `qa_mode`; 422 when `merge_mode == auto` and
  `qa_mode != browser`; 422 for `browser` when the project has no runbook
  with a `qa` section and no `host_git` repo.
- Worker `_attempt`: `off` → after collect + scope + secret checks + push,
  clean check, Done + `awaiting-merge`, no gates, no QA. `gates` → gates,
  clean check, Done + `awaiting-merge`, no QA, no criteria requirement, no
  spec, no evidence. Comments in Indonesian state what was and was not
  checked. Merge: QA re-run only in `browser`.
- Tests for all three modes and the validation.

## Task 4: runbook model, API and gates from the runbook

- `kemudi_ai/awak/runbook.py`: pydantic models per the design (apps,
  services with kind `process` only in 1a — `compose` accepted by the
  schema but refused at run time with a clear "stage 1b" message — env
  names, seed, qa {service, routes?}). Validation: names `[a-z0-9-]`,
  unique; `repo` must be a project repo name; `dir`/`file` relative, no
  `..`, no leading `/`; commands parse with shlex and argv[0] is on the
  runner allowlist (share the list via a constant in `runbook.py`, keep the
  runner's own copy and a test that they match); env names not in the
  blocked set; `{services.<name>.url}` placeholders must name a service;
  `qa.service` must be a `process` (or compose) service.
- Table `awak_runbooks` (project_slug PK, spec JSON, version, approved_by,
  approved_at, updated_by, updated_at). `GET /runbook` (member) returns
  `{runbook|null, version, approved_by, approved_at}`; `PUT /runbook`
  (admin) validates (422 with the pydantic errors as readable strings),
  bumps the version, sets approved_by/at to the saver.
- `kemudi_ai/awak/checks.py`: `install_payloads(cfg, runbook, repo_name)`
  and `gate_payloads(cfg, runbook, repo_name, changed_files)` returning a
  list of runner payloads `{subdir, commands, env}`: with a runbook, the
  apps of that repo (gates: apps whose `dir` contains a changed file; a
  root-level change or no match → all apps); without one, today's repo-row
  `_commands`. Worker and merge both use it (merge re-check passes the
  branch's changed files). Gates run per app in order and stop at the
  first failing app; gate names are prefixed with the app name.
- Runner `install`/`gates`: accept `env` (string→string, names validated
  against the blocked set) merged into the child env; add
  `npm_config_store_dir=/pnpm-store` to every child env.

## Task 5: process services in runner QA

- Runner `qa` op accepts `services`: `[{name, cwd (subdir), argv, env,
  health, ready_timeout}]` and `base_service`. For each: allocate a port
  from 5200 upward, substitute `{port}`, start with `start_new_session`,
  env = clean child env + `PORT` + service env + `NEXT_TELEMETRY_DISABLED=1`
  + `NODE_OPTIONS=--max-old-space-size=2048`, stdout/stderr to
  `.qa/logs/<name>.log`. Wait for health (status 200–399) at
  `http://localhost:<port><health>` up to `ready_timeout` (cap 600). On
  failure return `infra_error` with the last 60 lines of that log. After
  health, GET each path in `.qa/routes.txt` (max 10, 180 s each) to warm
  up. Base URL `http://localhost:<port>`. No storageState unless a token
  is given (Kemudi path). Stop every service by process group in
  `finally` (SIGTERM, then SIGKILL after 10 s). `{services.<name>.url}`
  in later services' env resolves to `http://localhost:<port>` of earlier
  ones (the order is the runbook's).
- `playwright.config.cjs`: `storageState` only when `QA_STATE` is set.
- Orchestrator `_qa`: with a runbook and `qa_mode == browser`, build the
  services payload from the runbook (process services only; compose →
  Infra "stage 1b") and call `qa` without token; `qa_task` gets the base
  URL hint, app dirs, "write the paths you visit to `.qa/routes.txt`" and
  "the spec runs twice against the same data". Kemudi without runbook
  stays on the vite path. Merge `_rerun_qa` the same.
- Runner op deadline: `qa` total under 1700 s (spec runs get the rest).
- Compose: runner `mem_limit: 4g`.
- Tests: runner test starting a tiny `python -m http.server` as a process
  service (health, log file, stop); orchestrator payload tests.

## Task 6: web (impeccable skill)

- `lib/kemudi-ai/agent.ts`: `qa_mode` on settings; `useRunbook`,
  `useSaveRunbook`; repo check response `apps`.
- Merge policy card: QA mode segmented control (Off / Gates only / Browser)
  with one-line explanations; auto merge disabled unless Browser (and the
  server's 422 shown).
- Runbook card: empty state ("No runbook yet. Configure automatically
  arrives in a later update; you can paste one.") + summary (apps with dir
  and commands, services, version, approver) + "Edit JSON" dialog with
  server validation errors listed.
- Repo form: after Check, show detected apps.
- en + id strings. Tests for the QA-mode control and the runbook card.

## Task 7: verify and ship 1a

- All test suites green; rebuild orchestrator, runner, web; restart only
  with no running job.
- Live: Kemudi regression (one small story on the vite path, or at least
  re-run gates via merge-less path) and playfast: Check pf-web (subdir
  `frontend`, commands filled), QA mode Gates only, unblock #1, watch it
  reach Done + awaiting-merge with real gates.
- Independent review subagent, fixes, PR, CI, merge, delete branch.
