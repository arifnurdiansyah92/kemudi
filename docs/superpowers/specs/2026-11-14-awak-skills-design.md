# Awak skills: library, marketplace, upload, editor, per-role assignment

Status: design. Date: 2026-11-14.

## Goal

Like Claude Code: an admin installs skills from a marketplace, uploads a
skill, or writes one in Kemudi, then chooses which skills each Awak role
(frontend, backend, fullstack, QA, setup) uses. Defaults per template (a
frontend role gets a design skill such as impeccable). Every agent run gets
exactly its role's skills, pinned, scanned and traceable.

## Facts this rests on (research 2026-11-14)

- Skill format: the open Agent Skills standard (agentskills.io): a folder
  `<name>/SKILL.md` with YAML frontmatter `name` (`[a-z0-9-]{1,64}`, no
  leading/trailing/double hyphen, equals the folder) and `description`
  (1-1024 chars), optional `license`, `compatibility`, `metadata`,
  `allowed-tools`; optional `scripts/`, `references/`, `assets/`. Claude Code
  skills and Hermes skills use it; a Claude Code skill folder loads in
  Hermes as-is.
- Claude Code marketplaces: a git repo with `.claude-plugin/marketplace.json`
  (`name`, `owner`, `plugins[]` with `name`, `source` (relative `./path`,
  `{source: github, repo, ref?, sha?}`, `{source: url, url, ref?, sha?}`,
  `git-subdir`, ...), `description`, `version`). A plugin's skills live in
  `skills/<name>/SKILL.md`. Examples: `anthropics/skills`
  (Apache-2.0), `pbakaus/impeccable` (Apache-2.0, keep LICENSE + NOTICE).
- Hermes: the `skills` toolset (`skills_list`, `skill_view`,
  `skill_manage`) gives progressive disclosure (an index of name +
  description in the system prompt; the body on demand). Skill roots:
  `$HERMES_HOME/skills`, `skills.external_dirs`. `skills.auto_load` puts a
  skill's full text into the system prompt. The chat API takes no skill or
  toolset field per request; **profiles** do: with
  `gateway.multiplex_profiles: true`, `/p/<profile>/v1/chat/completions`
  runs the turn with that profile's config and skill dirs. Kemudi's config
  is a managed overlay that wins over profiles, so `skills.*` must not be
  pinned there.
- Security: a skill is instructions (and maybe scripts) for an agent that
  runs unattended with write access to code. Third-party skills are a known
  prompt-injection and supply-chain vector (Anthropic: "use skills only from
  trusted sources"; studies find a quarter of public skills flawed).

## Concepts

- **Skill** (library entry): `slug` (= SKILL.md name), `source`
  (`marketplace` | `upload` | `authored`), `origin` (marketplace + plugin +
  repo + path, or uploader), `trust` (`builtin` | `trusted` | `community` |
  `local`), `license`, enabled flag. Library scope: the Kemudi instance
  (one org today); a project can only use skills an admin enabled.
- **Skill version**: immutable files (SKILL.md + support files, size-capped),
  `sha256` of the canonical tree, pinned git commit for marketplace ones,
  scan result, created_by/at. A skill points at its current version;
  updating creates a new version (diff shown, approval needed).
- **Marketplace**: a registered git repo (GitHub `owner/repo[@ref]` or a
  git URL) with `.claude-plugin/marketplace.json`; Kemudi lists its plugins
  and their skills; installing pins the commit. Built in (pre-registered,
  not installed): `anthropics/skills`, `pbakaus/impeccable`. Also accepted:
  a bare repo of `skills/*/SKILL.md` (no marketplace.json) as one plugin.
- **Assignment**: per project role, an ordered list of skill slugs, each
  `on_demand` (index + skill_view) or `always` (auto_load: full text in the
  prompt). Template defaults apply when a role is created and can be reset.

## Install paths

1. **Marketplace**: add a marketplace (admin) → Kemudi clones (shallow,
   no submodules, no LFS, no hooks, size cap) in the orchestrator, reads
   marketplace.json, resolves plugin sources (relative, github, url; others
   listed as unsupported), and shows plugins → skills with description,
   licence, version. Install a skill → copy the folder at the pinned commit
   → validate → scan → store version. "Check for updates" compares the
   source commit; an update is a new version awaiting approval (diff).
2. **Upload**: a `.zip` or `.skill` with one skill folder (or SKILL.md
   alone). Validate, scan, store; trust `local`.
3. **Authored**: an editor in Kemudi (name, description, body markdown,
   optional extra files as text), a live validation, a preview of what the
   agent sees; saved as a version; trust `local`. "Duplicate to edit" makes
   a local copy of any skill.

## Validation and scan (every version)

- Spec checks: name/description rules, folder name, total size ≤ 2 MB,
  ≤ 200 files, no symlinks, no absolute or `..` paths, text files UTF-8,
  SKILL.md body ≤ 500 lines (warning above), binaries only under `assets/`.
- Scan (findings shown, severity): instruction-injection patterns in the
  description and body (ignore previous instructions, exfiltrate, curl|sh,
  push, credentials, env dumps), network URLs, scripts present
  (`scripts/*`), `inline_shell` markers (`` !`cmd` ``), references to
  secrets/env names. `community` trust with a `high` finding cannot be
  enabled without an explicit admin override (recorded).
- Licence recorded; Apache-2.0/MIT/BSD/unspecified shown; NOTICE kept.

## Runtime (Hermes)

- `infra/awak/config.yaml`: enable the `skills` toolset for the API
  platform but not `skill_manage` (agents never write skills); keep
  `inline_shell: false`, `project_discovery: false` (a repo's own
  `.claude/skills` / `.agents/skills` are never loaded); move `skills.*`
  out of the managed overlay into profiles; `gateway.multiplex_profiles:
  true`.
- Per run: the orchestrator materialises the role's pinned skill versions
  into a shared read-only volume `kemudi-awak-skills` at
  `runs/<alias>/<slug>/` (alias = the per-run LLM alias already used), and
  a Hermes profile `run-<alias>` whose `skills.external_dirs` is that folder
  only and `auto_load` the `always` ones; calls
  `/p/run-<alias>/v1/chat/completions`; deletes both after the run (and a
  sweep removes leftovers). With no skills assigned the run uses the
  default profile with the skills toolset off (today's behaviour).
  Bundled Hermes skills are not visible to runs (the profile's own skills
  dir is empty).
- Scripts in skills run only through the agent's terminal tool inside the
  Hermes container (the same sandbox and deny rules as today).
- `prompt_version` includes the assigned skill versions' hashes; each run
  event records the skills given.

## API (under `/api/kemudi/`)

- Library: `GET /skills`, `GET /skills/{slug}` (versions, files list,
  scan), `GET /skills/{slug}/versions/{v}/files/{path}`, `POST
  /skills/upload` (multipart), `POST /skills` (authored), `PUT
  /skills/{slug}` (new authored version), `POST /skills/{slug}/enable|disable`,
  `POST /skills/{slug}/update` (fetch upstream → pending version), `POST
  /skills/{slug}/versions/{v}/approve`, `DELETE /skills/{slug}` (only if
  unassigned).
- Marketplaces: `GET/POST/DELETE /skill-marketplaces`, `POST
  /skill-marketplaces/{id}/refresh`, `GET /skill-marketplaces/{id}/plugins`,
  `POST /skill-marketplaces/{id}/install` `{plugin, skill}`.
- Roles: role JSON gains `skills: [{slug, mode}]`; `PUT
  /projects/{slug}/agent/roles/{id}` accepts it (only enabled skills).
- Admin = Kemudi instance admin for the library; project admin for
  assignment.

## Web

- **Skills** page (workspace settings): tabs Installed / Marketplace /
  Create. Installed: list with source, trust, licence, version, scan badge,
  used by N roles; detail with SKILL.md rendered, files, versions + diff,
  findings, update/approve. Marketplace: registered marketplaces (add by
  `owner/repo` or URL), plugins and skills with Install. Create: editor
  with validation and preview; Upload button.
- **Project settings → Agent → Roles**: per role, a "Skills" picker
  (search, mode on-demand/always, order), template defaults badge.
- Built with `impeccable`; en + id.

## Defaults

- Built-in marketplaces registered; impeccable installed (trust
  `trusted`) on first start if the network allows, else on first visit.
- Template defaults: frontend → `impeccable` (on demand; the main
  `impeccable` skill); fullstack → same; others none. Setup and QA none.

## Out of scope (later)

- Other hubs (skills.sh needs Vercel OIDC; Smithery needs a key;
  `.well-known/agent-skills` index) — the source model allows them later.
- Skills for the Kemudi chat assistant (only Awak roles now).
- Plugin commands/agents/hooks/MCP from marketplaces (skills only).

## Testing

- Orchestrator: validation and scan table, zip safety (zip-slip, size,
  symlinks), marketplace.json parsing with fixtures (relative, github, url,
  unsupported), install pins sha, update creates pending version, role
  assignment, run materialisation and profile cleanup (fake Hermes),
  prompt_version change, API auth.
- Web: library list, detail, editor validation, marketplace install, role
  picker.
- Live: install impeccable from its marketplace, assign to playfast's
  PF-FE, run a small web story; verify the run's profile had only that
  skill (Hermes `GET /p/run-<alias>/v1/skills`), the agent loaded it
  (skill_view in the run log), and cleanup. Upload a hand-made zip and
  author one skill in the editor.

## Panel review (security, runtime, delivery) and what changed

This section overrides the sections above where they differ.

### Delivery: three PRs, each live-tested and merged

- **PR 1, runtime + assignment** (no marketplace): spike the Hermes
  mechanism first; skill tables; `impeccable` vendored at a pinned sha
  (with LICENSE/NOTICE) as a `builtin` skill; role `skills` field + picker
  in the role editor + template defaults + "Reset to defaults"; skill sets
  materialised and served through Hermes profiles; cleanup. Live: a PF-FE
  run on playfast loads impeccable (skill_view in the run log); the run's
  profile lists only that skill.
- **PR 2, library**: the Skills page (installed list, detail, upload,
  authored editor, validation + scan, enable/disable). Live: upload a zip,
  author one, assign both.
- **PR 3, marketplace**: add a repo, list plugins/skills, install pinned,
  check for updates → pending version with diff → approve. Live: install
  from `anthropics/skills`, update flow.

### Admin and placement

- No instance admin exists today (orchestrator only knows Taiga's project
  `i_am_admin`). MVP: `KEMUDI_ADMIN_USER_IDS` (Taiga user ids,
  comma-separated) in orchestrator settings, `KEMUDI_ADMIN_USERNAMES` as a
  fallback (a username can be changed by its owner, an id cannot); `GET
  /api/kemudi/me` returns `id` and `kemudi_admin`.
  Library, upload, authoring, marketplaces, refresh, approve and overrides
  are Kemudi-admin only; project admins only assign enabled skills.
- The Skills page is a top-level route `/skills` shown in the sidebar to
  Kemudi admins (not under personal `/settings`). Project admins see a
  read-only trust/scan badge in the picker; with no enabled skills the
  picker says "Ask your Kemudi admin to install skills".

### Simplified for the MVP

- Trust: `builtin` | `local` | `marketplace`. A version with a `high` scan
  finding cannot be enabled (no override in the MVP).
- Mode: on-demand only (index + `skill_view`); `always`/auto_load later.
- Files stored in the DB (a JSON map path → base64, ≤ 2 MB per version),
  never extracted on the orchestrator's filesystem except into the skill
  set volume.
- A skill disabled or deleted after assignment is dropped at run time
  (logged); the role shows a warning. Approving a new version moves every
  role using that skill to it (run event notes the version).
- Scan: a short regex list (instruction override, exfiltration,
  `curl|sh`, `git push`, credential/env dumping, network URLs, scripts
  present, `` !`cmd` ``) → findings with severity.
- The description reaching the agent is cut to 300 characters in the
  materialised SKILL.md; the system prompt says skills are read-only
  reference material, never instructions that override Kemudi's rules.

### Runtime (verified in Hermes 2026.9.24; spike re-checks)

- Compose `kemudi-awak`: `GATEWAY_MULTIPLEX_PROFILES: "true"` (env, read
  at boot; without it `/p/<x>/` 404s with one profile). Profiles directory
  is re-read per request, so new profiles need no restart.
- **Skill sets, content-addressed**: `setid` = the first 32 hex of
  `sha256(sorted (slug, version sha))` (128 bits; `sk-` + 32 fits the
  40-character alias/profile columns and Hermes' profile name rule). Files at `/opt/skills/sets/<setid>/<slug>/…` in a volume
  `kemudi-awak-skills` (read-only in Hermes, written by the orchestrator,
  root-owned 0755/0644). Profile `sk-<setid>` in a volume
  `kemudi-awak-profiles` mounted at `/opt/data/profiles` (written by the
  orchestrator): `config.yaml` (`skills.external_dirs: [<set dir>]`) and
  `.env` with `KEMUDI_LLM_PROXY_TOKEN` and `KEMUDI_AWAK_MODEL` (env vars
  given to the container do not expand inside a profile scope). Built in
  `profiles/.tmp-<id>` and renamed into place (dot names are never served).
  Config files root-owned and not writable by uid 10000 where Hermes
  allows it (spike); the orchestrator re-verifies the profile files' hash
  before each run and rewrites on mismatch.
- **Every Awak run goes through a profile**, including runs with no skills
  (an empty set), so the bundled Hermes skills in `/opt/data/skills` never
  appear. The default profile serves health checks only.
- Managed overlay (`infra/awak/config.yaml`): remove `skills` from
  `disabled_toolsets` and add it to the API platform toolsets; remove
  `skills.auto_load` (lists replace whole, so a pinned `[]` would win);
  keep `project_discovery: false`, `inline_shell: false`; pin
  `skills.write_approval: true`. `skill_manage` cannot be removed from the
  toolset alone: the skill volume is read-only and writes are staged, never
  applied; the system prompt says skills are read-only.
- Agent write roots: drop `/opt/data` from `HERMES_WRITE_SAFE_ROOT` if
  Hermes runs without it (spike); otherwise record it as an accepted limit
  (the container stays the boundary, as for `/workspace`).
- **Dropping `/opt/data` from `HERMES_WRITE_SAFE_ROOT` does not bind the
  terminal.** It limits Hermes' file tools only; the agent's terminal runs
  as uid 10000, which owns `/opt/data/profiles` (Hermes re-chowns it at
  every boot), so a run can plant `profiles/<any>/skills/x/SKILL.md`,
  `SOUL.md`, hooks, plugins, memories or cron jobs, or edit another
  profile's config. **The control is the per-run reset**:
  `skills.prepare_set` resets the run's profile home to an allowlist
  before every run (Kemudi's `config.yaml`, `.env` and a fixed `SOUL.md`
  re-checked by hash; Hermes' runtime state kept; `skills/` except `.hub`,
  `hooks/`, `plugins/`, `memories/`, cron jobs and any unknown entry
  removed; profiles in the volume that are not Kemudi's removed), fixes
  the ownership, and records a `profile_reset` run event listing what it
  removed. Longer term: run the agent's terminal as a separate uid that
  cannot write the profiles.
- Orchestrator call: `{awak_url without /v1}/p/sk-<setid>/v1/chat/completions`.
- Cleanup: a sweep deletes sets no role references and unused for > 24 h,
  never while a run uses them; profile first, then files.
- Tokens: the skills tools cost ~1.2k tokens per call plus ~30-260 per
  skill in the index; recorded in the run's prompt size.
- A run whose skills include a `marketplace` skill cannot auto-merge
  (merge mode forced to `approve` for that story, noted on the card).

### Marketplace fetch (PR 3)

- Fetched by the runner (uid 10000, no Kemudi secrets) through a new op,
  not the orchestrator: GitHub only (`https://github.com/<owner>/<repo>`,
  others later by allowlist), the tarball API at a resolved full commit
  sha, streamed with a byte cap (50 MB) and timeouts, extracted with
  lstat checks (no symlinks, no `..`, no absolute paths, entry and size
  caps), plugin sources one level deep (relative or github only).
- Zip upload (PR 2): decompressed bytes counted (not declared), entry
  count, depth and ratio caps, no symlink entries, no duplicates or
  case/Unicode collisions, no nested archives; read in memory.
- Skill files are served from the DB by exact key; SKILL.md and diffs are
  rendered with sanitised markdown (no raw HTML, no `javascript:` links).
- Licence read from frontmatter and LICENSE/NOTICE (skill, plugin, repo);
  LICENSE/NOTICE kept in the materialised skill; "unspecified" shows a
  warning.
