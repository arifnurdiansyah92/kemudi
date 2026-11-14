# Plan: Awak skills PR 3 (marketplace)

Design: `docs/superpowers/specs/2026-11-14-awak-skills-design.md` ("Panel
review" → "Marketplace fetch" overrides). PRs 1-2 merged: runtime, roles,
library page, upload, authoring, scan, `store_version`, `findings_rise`.
Branch `feat/awak-skills-marketplace`.

## Task 1: fetch in the runner (no Kemudi secrets)

- Runner op `fetch_repo {owner, repo, ref?}`: GitHub only. Resolve `ref`
  (default branch if empty) to a full commit sha via
  `https://api.github.com/repos/<o>/<r>/commits/<ref>` (no token; handle
  rate-limit errors), then download
  `https://codeload.github.com/<o>/<r>/tar.gz/<sha>` streamed with a 50 MB
  cap and timeouts; extract into `/workspace/.skills-fetch/<random>/` as uid
  10000 with lstat checks (regular files and dirs only, no symlinks or
  hardlinks, no `..`/absolute, entry and size caps). Returns `{sha, dir}`
  (relative path) or `{error}`. `fetch_cleanup {dir}`. Host and IP rules:
  only `api.github.com` and `codeload.github.com` (no redirects followed
  elsewhere). Runner tests with a local fake HTTP server or monkeypatched
  opener.
- Orchestrator reads files from the fetched tree through the shared
  workspace volume (read-only use, lstat again), never executes anything.

## Task 2: marketplaces and install

- Table `awak_skill_marketplaces` (id, name, owner/repo, ref, builtin,
  last_sha, last_fetched_at, error, created_by/at). Builtins registered on
  start (not fetched): `anthropics/skills`, `pbakaus/impeccable`.
- Parse `.claude-plugin/marketplace.json` (name, owner, plugins[] with
  `name`, `source`, `description`, `version`, `category`); plugin sources:
  relative `./path` (no `..`), `{source: "github", repo, ref?, sha?}`
  (fetched as a second repo, one level deep); others listed as
  unsupported with the reason. A repo without marketplace.json but with
  `skills/*/SKILL.md` (or `*/SKILL.md` at root) is one plugin. Skills of a
  plugin: `skills/<name>/SKILL.md` under the plugin root (also a plugin
  whose root itself is a skill). Licence from SKILL.md, plugin dir, repo
  LICENSE/NOTICE (kept with the skill files).
- API (Kemudi admin): `GET/POST/DELETE /api/kemudi/skill-marketplaces`
  (`POST {repo: "owner/repo[@ref]" | "https://github.com/owner/repo"}`),
  `POST /…/{id}/refresh` (fetch, cache the listing with sha), `GET
  /…/{id}/plugins` (cached listing: plugins → skills with name,
  description, licence, version, installed slug/version if any, supported
  flag), `POST /…/{id}/install {plugin, skill}` → validate + scan +
  `store_version` (source `marketplace`, origin {marketplace, repo, sha,
  plugin, path}); disabled after install (admin enables). Slug clash with
  a local/builtin skill → 409.
- Updates: `POST /api/kemudi/skills/{slug}/check-update` (marketplace
  skills): refetch the origin repo at its ref; if the skill folder's
  canonical sha changed → a `pending` version (not current) with a diff
  summary (files added/removed/changed, scan); `POST
  /api/kemudi/skills/{slug}/versions/{v}/approve` makes it current
  (findings_rise rule applies); `…/reject` deletes it. Runs never use
  pending versions.
- Runs with a marketplace skill force approve (already in place).
- Tests: marketplace.json fixtures (relative, github, unsupported, missing
  file → skills dir fallback), install pins the sha, clash, update →
  pending → approve/reject, authz, fetch failure states.

## Task 3: Web (impeccable; screenshots only, never click settings)

- Skills page gets a **Marketplace** tab: registered marketplaces (builtin
  badge, last refresh, error), "Add marketplace" (owner/repo), refresh;
  plugins → skills list with description, licence, version, Install /
  Installed vN; unsupported sources greyed with the reason.
- Detail of a marketplace skill: origin (repo@sha link), "Check for
  update", pending version card with diff summary + findings, Approve /
  Reject.
- en + id; vitest.

## Task 4: verify and ship

- Live: refresh `anthropics/skills`, install one skill (e.g. a small
  documentation/writing skill), enable, check its files and licence;
  check-update shows "up to date"; refresh `pbakaus/impeccable` lists the
  impeccable plugin skills. Fetch of a non-GitHub URL refused.
- Review subagent, fixes, PR, CI, merge.
