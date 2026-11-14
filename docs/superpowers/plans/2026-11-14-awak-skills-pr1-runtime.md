# Plan: Awak skills PR 1 (runtime + role assignment)

Design: `docs/superpowers/specs/2026-11-14-awak-skills-design.md`; the
"Panel review" section overrides. Branch `feat/awak-skills-runtime`.
Commit per task; tests per task (orchestrator pytest, web vitest).

## Task 0: spike (no product code; findings into the plan's notes)

On the running stack, prove with a throwaway profile written by hand:
- `GATEWAY_MULTIPLEX_PROFILES=true` on kemudi-awak; `/p/sk-test/v1/models`
  answers; a profile created after boot is served without a restart.
- A profile with `.env` (proxy token, model) + `config.yaml`
  (`skills.external_dirs: [/opt/skills/sets/test]`) runs a chat completion
  through Kemudi's LLM proxy (the proxy sees the real token).
- With the managed-overlay changes (skills toolset on, `auto_load`
  removed, `write_approval: true`), `GET /p/sk-test/v1/skills` lists only
  the set's skills (no bundled ones); the default profile's list is
  irrelevant (runs never use it).
- Which profile files Hermes writes at runtime (so config files can be
  root-owned read-only), and whether removing `/opt/data` from
  `HERMES_WRITE_SAFE_ROOT` breaks a run.
Record results in `## Spike notes` at the end of this file. If profiles do
not work, stop and report (fallback: skill text in the system prompt).

## Task 1: data + builtin skill

- Tables `awak_skills` (slug PK, source `builtin|local|marketplace`,
  title, description, license, enabled, current_version, origin JSON,
  created_by/at, updated_at) and `awak_skill_versions` (id, slug, version
  int, sha256, files JSON path→base64, size, scan JSON, created_by/at,
  status `active|pending`). `AwakRole.skills` JSON list of slugs (default
  `[]`). Migration via the existing `_migrate`.
- `kemudi_ai/awak/skills.py`: validate (agentskills rules + Kemudi limits),
  scan (short regex list → findings), canonical sha, `materialise(set)`.
- Vendored `impeccable` (from `pbakaus/impeccable` at a pinned commit;
  only the skill folder(s) the plugin exposes, plus LICENSE and NOTICE)
  under `apps/orchestrator/kemudi_ai/awak/builtin_skills/`, seeded at
  start as `builtin` (idempotent; a new vendored sha → new active version).
- Settings: `KEMUDI_ADMIN_USERNAMES`; `GET /api/kemudi/me` →
  `{kemudi_admin}`.

## Task 2: runtime

- Compose: `GATEWAY_MULTIPLEX_PROFILES: "true"` on kemudi-awak; volumes
  `kemudi-awak-skills` (ro in awak at `/opt/skills`, rw in orchestrator)
  and `kemudi-awak-profiles` (`/opt/data/profiles` in awak, rw in
  orchestrator); `infra/awak/config.yaml` overlay changes per the design.
- `skills.prepare_set(role_skills) -> profile_id`: setid from (slug,
  sha); write files under `/opt/skills/sets/<setid>/` (description cut to
  300 chars in SKILL.md; LICENSE/NOTICE kept), profile `sk-<setid>` with
  config.yaml + .env via `.tmp-` + rename; verify hash before each run;
  disabled/missing skills dropped (event).
- `HermesAgent.run(..., profile=...)` calls `/p/<profile>/v1/chat/completions`;
  every Awak call (code, QA, setup) passes a profile (empty set when no
  skills). System prompt line: skills are read-only reference material.
- `prompt_version` includes the setid; the run event records the skills.
- Sweep: unreferenced sets unused > 24 h (profile then files), never while
  a run uses them.
- Merge mode forced to approve when a run used a `marketplace` skill (no
  such skills exist in PR 1; the check is in place).

## Task 3: API + web

- Role JSON gains `skills: [slug]`; PUT validates enabled skills only;
  template defaults (frontend, fullstack → `impeccable`); `POST
  /roles/{id}/skills/reset`. `GET /api/kemudi/skills` (enabled, for the
  picker: slug, title, description, source, license, scan badge).
- Web (impeccable): role editor "Skills" picker (search, add/remove, badges,
  empty state, reset to defaults); en + id; vitest.

## Task 4: verify and ship

- Live on playfast: assign impeccable to PF-FE; a small web story; the run
  log shows `skill_view impeccable`; `GET /p/sk-<id>/v1/skills` lists only
  it; QA passes; cleanup sweep works.
- Review subagent, fixes, PR, CI, merge.

## Spike notes

Run 2026-11-14 on the dev stack (Hermes image `kemudi/kemudi-hermes:dev`),
throwaway profiles `sk-test*` and set `/opt/skills/sets/test` (one skill
`spike-hello`), written from the orchestrator container as root; removed
afterwards. Profiles work; the design holds with the changes below.

- `GATEWAY_MULTIPLEX_PROFILES=true` on kemudi-awak: `/p/<id>/v1/models`
  answers for a profile created after boot. **But a new profile is only
  served (turns run) after the reconcile watcher picks it up, every 30 s**
  (or a control-socket rescan, which the orchestrator cannot reach). Before
  that a chat completion gets `409 profile_mismatch` while `/v1/models`
  already says 200. Served = Hermes created `gateway.lock` (and `state.db`)
  in the profile dir. The orchestrator therefore waits (polls the shared
  volume for `gateway.lock`, ≤ 90 s) after creating a profile, and retries a
  `409 profile_mismatch` a few times.
- **The profile `.env` needs `API_SERVER_KEY`** (the gateway checks the
  profile-scoped key on `/p/<id>/`; without it every request is 401), plus
  `KEMUDI_LLM_PROXY_TOKEN` and `KEMUDI_AWAK_MODEL` (the managed overlay's
  `${...}` expand from the profile's scope). With these a chat completion
  through `/p/sk-test3/` reached Kemudi's proxy (`awak_llm_aliases`
  `upstream_ok` 2-3, no errors) and the model answered from the skill.
- **The profile dir must be owned by uid 10000 (hermes)**: a root-owned dir
  is parked at the first serve attempt (`gateway.lock: No such file`) and a
  parked profile is never retried by the watcher (then `503
  runtime_draining`). The orchestrator builds `profiles/.tmp-<id>`, chowns
  it to 10000 and renames it into place. Also Hermes' boot hook runs `chown
  -R hermes` over `/opt/data/profiles` on every start, so **root-owned
  read-only config files are not possible**: accepted limit, the
  orchestrator re-hashes `config.yaml` + `.env` before every run and
  rewrites on mismatch (the container stays the boundary, as for
  `/workspace`). Hermes itself never rewrote them during runs.
- Runtime files Hermes writes into a served profile: `gateway.lock`,
  `state.db*` (~1.5 MB), `SOUL.md`, `.skills_prompt_snapshot.json`,
  `sessions/`, `logs/`, `cache/`, `cron/`, `skills/.hub/` (no bundled
  skills), `pending/skills/` (staged `skill_manage` writes), `memories/`,
  `platforms/`, `plugins/`, `hooks/`, `backups/`, `runtime/`.
- Overlay (skills toolset on for `api_server`, removed from
  `disabled_toolsets`, `auto_load` removed, `write_approval: true`): the
  profile lists only the set's skill (`hermes -p sk-test skills list` →
  `spike-hello`, source external; the default profile lists 39 bundled
  ones, irrelevant). `skill_view spike-hello` loads from
  `/opt/skills/sets/test`; `skill_manage create` is staged under
  `pending/skills/<id>.json`, never applied.
- **`GET /v1/skills` (and `/p/<id>/v1/skills`) is broken in this Hermes
  build**: 500, `find_all_skills() got an unexpected keyword argument
  'include_editorial'` (api_server.py calls it with an argument
  `tools/skills_tool.py` does not take). Verification uses
  `docker exec -u hermes kemudi-dev-kemudi-awak-1 hermes -p sk-<setid>
  skills list` instead (same `find_all_skills` catalog, profile-scoped).
- `HERMES_WRITE_SAFE_ROOT=/workspace` (without `/opt/data`): a run still
  works (`write_file` to `/workspace/...` ok, `skill_view` ok, Hermes'
  own state writes are not file-tool writes). Dropped `/opt/data`.
- Deleting a served profile dir is safe (the watcher unserves it;
  `/p/<id>/v1/models` → 404). The default profile keeps serving `/health`.
