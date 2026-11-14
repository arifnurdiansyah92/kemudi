# Plan: Awak stage 1c (Setup Assistant, "Configure automatically")

Design: `docs/superpowers/specs/2026-11-14-awak-workspace-runbook-design.md`
section 6 (Setup Assistant), the Data/API/Web sections and the "Panel
review" section (overrides). 1a and 1b are merged: workspaces, runbook
(process + compose services, init, seed, run_in, qa.login), vault,
kemudi-dind/kemudi-svc, `checks.py`, `qa_mode`.

Tests as in 1a/1b. Commit per task.

## Task 1: setup run model and state machine (backend)

- Table `awak_setup_runs` (`id`, `project_slug`, `state`, `round`,
  `proposal` JSON, `steps` JSON list of `{name, ok, output}` (output is a
  redacted tail ≤ 4 KB), `missing_env` JSON list of
  `{name, description, secret}`, `screenshot` (path under
  `/workspace/<slug>/setup/`), `resources` JSON, `error`, `cost_idr`,
  `created_by`, `created_at`, `updated_at`). Add to `_MIGRATED_TABLES`
  handling as the other awak tables do.
- `kemudi_ai/awak/setup.py` with `SetupRunner(worker)` and one method per
  state; each call advances one step and persists (the worker serves one
  step per tick):
  - `queued → reading`: sync every repo, check out the default branch to
    `/workspace/<slug>/setup/<repo>/` (gitops `checkout_default`), run
    `detect.detect_apps` on each, store the draft in `proposal.draft`.
  - `reading → proving`: the setup agent (Hermes, new template `setup` in
    `prompts.py`, the project's model, read-only intent) gets the runbook
    JSON schema (`Runbook.model_json_schema()`), the compose allowlist,
    the draft, the rules (no secret values in the runbook, prefer the
    project's compose for backing services, dev servers over production
    builds for QA, use `generated` for build artefacts, `{changed:...}`
    for lint over a red baseline) and writes
    `/workspace/<slug>/setup/runbook.json`. Validate with
    `runbook.validate`; problems go back to the agent (max 2 more turns),
    then `failed`.
  - Missing env: every name the runbook references (`env`, `qa.env`,
    `{env.X}` in `qa.login`, compose service `env`) without a vault value
    → `needs_input` with `missing_env` (the agent's `env_help` gives
    descriptions; `secret` true unless the name is clearly not a secret).
    `POST /setup/{id}/env` writes values to the vault and moves the run
    back to `proving`. `needs_input` holds no resources.
  - `proving`: in the runner/svc, using the same helpers the worker uses
    for gates and QA (no duplicate code): install every app, run its
    checks once (record ok/red per check; red does not fail the run;
    "could not run" (missing tool, Unsupported) does), `svc_up` compose
    services, `init`, `seed`, start process services, health, one
    Playwright screenshot of `qa.service` `/` (runner op `screenshot`
    {path, services, base_service, out} that reuses the qa service
    startup), `svc_stats` + process RSS into `resources`, logs tail of
    each service, then `svc_down` and stop processes in `finally`.
  - Fix loop: a failed install, start or health goes back to the agent
    with the redacted logs ("fix the runbook"), max 3 rounds (`round`);
    then `failed` with the last logs.
  - `ready`: proposal + steps + screenshot + resources stored.
  - `approved` (human, via API): save as the project's runbook
    (version +1, `approved_by`, `approved_at`).
  - `cancelled`: services down first, checkout kept.
- Worker `tick`: after requested merges and before stories, one active
  setup run per project gets `SetupRunner.step(run)`. Worker start: a run
  stuck in `proving` is moved back to `proving` round start (resumable);
  sweep keeps its svc project `<slug>-setup`.
- Redaction: every step output, error and agent feedback passes the
  project's vault values + usual secrets; the agent never sees a value.
- Cost: agent cost goes to `cost_idr`.
- Tests with fake agent/runner/svc: happy path to `ready`; invalid JSON
  twice → `failed`; missing env → `needs_input` → env → `proving`; failed
  health → fix round → ready; 3 failed rounds → `failed`; cancel calls
  `svc_down`; red check does not fail; approve bumps the runbook version;
  redaction of a vault value in a step output.

## Task 2: API

Under `/api/kemudi/projects/{slug}/agent` (admin unless noted):
- `POST /setup` (one active run per project → 409 otherwise),
- `GET /setup/latest` (member),
- `POST /setup/{id}/env` `{values: {NAME: {value, secret}}}`,
- `POST /setup/{id}/approve` (only from `ready`; optional `qa_mode`),
- `POST /setup/{id}/cancel`,
- `GET /setup/{id}/screenshot` (member, authenticated, image/png, path
  checked under the project's setup dir).
Tests for each, including role checks and the 409.

## Task 3: Web (impeccable)

- Runbook card: "Configure automatically" button (admin) starts a run;
  "Edit JSON" stays as the advanced path.
- Setup Assistant panel: step timeline (Reading repos → Proposing →
  Waiting for env → Proving → Ready), live state (poll every 3 s while
  active), missing env form (name, description, secret toggle, values
  write-only), per-step results with expandable logs, screenshot,
  peak RAM/CPU, the proposed runbook summary (reuse the Runbook card's
  summary component), Approve (with "switch QA to Browser" checkbox) /
  Cancel, failure state with the last logs and "Try again".
- en + id strings in the `agent` namespace. Vitest for the panel states.

## Task 4: verify and ship

- Live on playfast: clear nothing (keep the 1b runbook as a reference),
  run Configure automatically, fill env when asked, check the proof
  (screenshot, RAM), approve, then a story run still passes gates.
- Review subagent, fixes, PR, CI, merge.
