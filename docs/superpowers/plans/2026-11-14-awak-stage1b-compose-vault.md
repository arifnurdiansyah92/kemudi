# Plan: Awak stage 1b (vault, sandboxed Docker, compose services, QA login)

Design: `docs/superpowers/specs/2026-11-14-awak-workspace-runbook-design.md`
(sections 2, 4, 5 and the "Panel review" section, which overrides). 1a is
merged: per-project workspaces, runner `path`, runbook with `process`
services, `checks.py`, `qa_mode`. Branch `feat/awak-compose-vault`.

Tests as in 1a. Commit per task.

## Task 1: vault

- Table `awak_env_vars` (id, project_slug, name, value_enc, secret,
  updated_by, updated_at; unique slug+name). Name `[A-Z_][A-Z0-9_]{0,63}`,
  not in the runbook's blocked set.
- `vault.py`: Fernet key derived with HKDF-SHA256 from `KEMUDI_SECRET_KEY`,
  info `awak-vault` (MultiFernet-ready); `put`, `delete`, `values(slug)`
  (decrypted dict), `redaction_values(slug)` (every value, any length ≥ 4,
  plus base64 and URL-encoded variants).
- API: `GET /env` (member: names, flags, non-secret values; secret →
  `{set: true}`), `PUT /env/{name}` `{value, secret}` (admin), `DELETE
  /env/{name}` (admin). Decision rows, no values in them.
- Worker: vault values join `secret_values` for the project being worked
  (comments, events, feedback to the agent, setup logs) and the diff scan
  (values ≥ 8 chars).
- Web: "Env & secrets" card (list, add/edit dialog, secret values
  write-only, "test/dev values only, never production" note). en + id.

## Task 2: runner hardening (uid split)

- Runner image: server runs as root with `cap_add: [SETUID, SETGID, KILL]`
  only (`cap_drop: ALL` stays), the key read from env at start; every child
  (`run`, process services, Playwright) runs as uid/gid 10000 via
  `subprocess(user=, group=, extra_groups=[])` with the clean env.
  `/proc/1/environ` is then unreadable to children. Workspace files stay
  owned by 10000. Update the docstring. Test: a child cannot read
  `/proc/1/environ` (skip when not root).

## Task 3: `kemudi-dind` and `kemudi-svc`

- Compose: `kemudi-dind` (`docker:27-dind`, privileged, `dockerd
  --host=unix:///run/dind/docker.sock --userns-remap=default
  --default-address-pool base=10.201.0.0/16,size=24`), volumes
  `kemudi-dind-sock:/run/dind`, `kemudi-dind-data:/var/lib/docker`;
  networks `kemudi-dindnet` (internal, shared with the runner) and
  `kemudi-egress`; `mem_limit: 5g`, `pids_limit: 2048`. Profile `awak`.
- `kemudi-svc`: new `infra/svc/` (Dockerfile `FROM docker:27-cli` + `apk
  add python3`, `svc.py` stdlib HTTP server, own key `KEMUDI_SVC_KEY`),
  mounts `kemudi-dind-sock` and `kemudi-awak-workspace:/workspace:ro`, a
  tmpfs `/run/svc` (0700) for env and normalized compose files; network
  `kemudi-svcnet` (internal) shared only with the orchestrator.
- Orchestrator: `svc_url`, `svc_key` settings; `SvcClient` like `HttpRunner`.
- `.env.example` documents `KEMUDI_SVC_KEY`; the dev `infra/.env` gets a
  generated value (append without printing the file).

## Task 4: compose sanitizer and svc ops (in `svc.py`)

- `svc_up {path, project, file, services, expose, env}`:
  1. `docker compose -f <file> --project-directory <dir> config
     --no-interpolate --format json` (env cleared: `env -i PATH=...`).
  2. Keep the selected services plus their `depends_on` closure.
  3. Allowlist check (design, Panel review): service keys `image`,
     `build{context,dockerfile,args,target}`, `command`, `entrypoint`,
     `environment`, `healthcheck`, `depends_on`, `working_dir`, `user`,
     named `volumes`, `tmpfs`, `expose`, `ports`, `restart`,
     `stop_grace_period`, `logging` (dropped), `networks` (dropped),
     `container_name` (dropped), `labels` (dropped). Anything else refuses
     with the key named. Top-level: `services`, `volumes` (no `driver`,
     `driver_opts`, `external`, `name`), `networks` (dropped), `name`
     (dropped); `include`/`extends`/`secrets`/`configs` refused.
     `build.context`/`dockerfile` resolve (no symlink components) inside
     the checkout.
  4. Write `<tmp>/compose.json` with interpolation done by compose itself:
     run `config --format json` on the reduced file with
     `--env-file <tmp>/vault.env` only, env cleared.
  5. Rewrite: `image: kemudi-<project>-<svc>` for built services,
     `restart: "no"`, `mem_limit` min(existing, 2g), `pids_limit: 512`,
     `ports` → only the `expose` port as `0.0.0.0::<port>`, labels
     `kemudi.project=<project>`.
  6. `docker compose -p <project> -f <tmp>/compose.json build` (deadline
     900 s), then `up -d --wait --wait-timeout 300` (pull missing images).
     Return `{url: http://kemudi-dind:<published>, logs_tail}`; on failure
     the redacted tail of `docker compose logs`.
- `svc_exec {project, service, argv, env?, timeout}`: `docker compose -p
  <project> -f <tmp>/compose.json run --rm --no-deps -T <service> <argv>`
  (deadline); returns exit + output tail.
- `svc_logs`, `svc_stats` (`docker stats --no-stream` filtered by label),
  `svc_down {project}` (`docker compose -p <project> down -v
  --remove-orphans`, delete its tmp files), `svc_sweep {keep: [projects]}`
  (down every labelled project not in keep; `docker image prune` of
  `kemudi-*` images not in use; `builder prune --keep-storage 10GB`).
- Unit tests for the sanitizer with JSON fixtures (no Docker): playfast's
  compose reduced to postgres/redis/backend passes; each refused key
  refused; `:?` var in an unselected service ignored. One integration test
  marked `docker` (skipped in CI) driving a real dind.

## Task 5: runbook additions and QA against compose

- Runbook schema: compose services (`repo`, `file`, `compose_services`,
  `expose: "svc:port"`, `health`, `env: [vault names]`, `ready_timeout`),
  `init: [{service, command}]` (run_in one-shots after backing services,
  before health wait), `seed`, `run_in: "<service>:<compose service>"` on
  apps, `qa.login: {path, fields: {selector: "{env.NAME}"}, submit,
  success_url?}`, `qa.env: [vault names]`. Placeholders `{env.NAME}` only in
  `qa.login.fields`.
- Worker/merge QA (`browser`): `svc_up` for compose services (project
  `<slug>-us<ref>`, vault values for their `env`), run `init` and `seed` via
  `svc_exec`, health check through the runner (`url + health`), then the
  runner `qa` op with process services (their env's
  `{services.x.url}` → the compose URL), `qa.login` (runner performs the
  form login once with Playwright and writes `storageState`), `qa.env`
  values passed only to the Playwright process. Always `svc_down` in
  `finally`. Logs of a failed start go to the event and the card
  (redacted).
- Gates for `run_in` apps: `svc_up` (build from the story checkout, no
  `--wait` for the app service itself), `svc_exec` each command, `svc_down`.
- Worker start: `svc_sweep` with the running job's project kept; runner
  kills leftover process services.
- `_qa_mode_blocker`/`browser_qa_ready`: compose services now count.

## Task 6: verify and ship

- Live on playfast: vault `JWT_SECRET_KEY`, `QA_ADMIN_EMAIL`,
  `QA_ADMIN_PASSWORD`; runbook with api (compose: postgres, redis,
  backend), init (create_all + admin user), web process with
  `INTERNAL_API_URL={services.api.url}`, `qa.login`; QA mode Browser;
  re-run #1 to Done with browser evidence; #3 gates via `run_in`.
- Leak check after: `docker ps -a`, `volume ls`, `system df` inside dind;
  no process services left in the runner.
- Review subagent, fixes, PR, CI, merge.
