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

(filled by Task 0)
