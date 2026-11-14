# Plan: Awak skills PR 2 (library: Skills page, upload, authoring)

Design: `docs/superpowers/specs/2026-11-14-awak-skills-design.md` ("Panel
review" overrides). PR 1 is merged: tables, `skills.py` (validate, scan,
sha, materialise, profiles), builtin impeccable, role assignment + picker,
`KEMUDI_ADMIN_USER_IDS` / `/api/kemudi/me` (`kemudi_admin`). Branch
`feat/awak-skills-library` from main.

## Task 1: API (Kemudi admin only unless noted)

- `GET /api/kemudi/skills/library` (admin): every skill (enabled or not)
  with source, licence, current version, scan level, `used_by`
  `[{project, role}]`, status of pending versions.
- `GET /api/kemudi/skills/{slug}` (admin; members get the picker summary
  only): versions (number, sha, size, created_by/at, status), current
  version's file list, findings, SKILL.md text, licence files.
- `GET /api/kemudi/skills/{slug}/versions/{v}/files/{path}` (admin): one
  file from the DB by exact key; text as JSON `{path, text}`, binaries as
  `{path, size, binary: true}` (no download in the MVP).
- `POST /api/kemudi/skills/upload` (multipart, `.zip` or `.skill` or a
  single `SKILL.md`): zip safety per the design (in memory, decompressed
  bytes counted, entry/depth/ratio caps, no symlinks, no duplicates or
  case/NFC collisions, no nested archives, one top-level skill folder or
  files at the root); validate + scan; new skill (source `local`) or a new
  version of an existing `local` skill with the same slug (409 for
  builtin/marketplace slugs); `?replace=true` required to add a version.
- `POST /api/kemudi/skills` (author): `{slug, description, body, files?:
  {path: text}}` → builds SKILL.md (frontmatter name/description + body),
  validate + scan, version 1 (source `local`). `PUT
  /api/kemudi/skills/{slug}` new version of a `local` skill.
- `POST /api/kemudi/skills/{slug}/enable|disable`: enabling refuses a
  current version with a `high` finding (422 listing them). Disabling a
  skill in use is allowed (roles show a warning; runs drop it).
- `DELETE /api/kemudi/skills/{slug}`: only unassigned, non-builtin (409 with
  `used_by`).
- `POST /api/kemudi/skills/validate` (admin): dry-run validate + scan for
  the editor (no store).
- Decision rows for every write (no file contents).
- Tests: zip safety table (zip-slip, symlink entry, bomb, nested zip,
  duplicate, case collision, too many files, too big), validation,
  scan → enable refusal, authoring round trip, versioning, delete rules,
  authz (non-admin 403), project picker unchanged.

## Task 2: Web (impeccable)

- Route `/skills` (top-level, `apps/web/src/routes/_authenticated/skills…`),
  sidebar entry only when `kemudi_admin`. Tabs: **Installed** and
  **Create**; an **Upload** button; a Marketplace tab placeholder is NOT
  added (PR 3).
- Installed: list (title, slug, source badge, licence or "unspecified"
  warning, version, scan badge, used by N, enabled switch). Detail
  drawer/page: SKILL.md rendered with sanitised markdown (no raw HTML, no
  javascript: links), files list with text viewer, versions, findings with
  severity, used-by list, delete.
- Create: editor (slug, description with counter, body markdown, extra
  text files), live validation (debounced `POST /skills/validate`), preview
  of the SKILL.md the agent gets (description cut to 300 chars), save.
- Upload: dialog with drop zone, shows validation/scan results; on a
  slug clash with a local skill offers "add as new version".
- en + id strings; vitest for list, detail, editor validation, upload.

## Task 3: verify and ship

- Live: upload a hand-made zip skill, author one in the editor, enable
  both, assign one to playfast's PF-BE, run a small backend story and see
  `skill_view <slug>` in the Hermes log; a zip with a symlink or a
  `curl … | sh` body is refused / flagged.
- Review subagent, fixes, PR, CI, merge.
