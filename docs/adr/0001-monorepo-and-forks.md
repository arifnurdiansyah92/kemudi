# ADR 0001: Monorepo, and how upstream forks are held

Date: 2026-11-10
Status: accepted

## Context

Kemudi replaces an internal deployment (`taiga-v2`) that ran the stock
`taigaio/*` Docker images and customised them by bind-mounting patched files
over the image (backend) and injecting HTML/JS into `index.html` at container
start (frontend). That works but is fragile: every upstream upgrade means
re-diffing the overlays by hand, and the frontend cannot be redesigned this way.

Kemudi needs to change the backend, build a new UI, and add an AI agent, all
in one place that is open source from the start.

## Decision

One monorepo with this layout: `apps/` for code we write, `services/` for
forks, `infra/` for deployment, `docs/`, `LICENSES/`.

- **taiga-back and taiga-events → git subtree** (`services/kemudi-back`,
  `services/kemudi-events`), not squashed, pinned to release tags 6.10.2 and
  6.10.0. Upstream history stays in this repo, so `git blame` works and newer
  releases merge with `git subtree merge`.
- **hermes-agent → git submodule** (`services/awak`) pointing at our GitHub
  fork. Upstream is ~1.4 GB, and copying it in would make every clone of
  Kemudi heavy. The submodule is marked `shallow = true`.
- **taiga-front is not forked.** The new UI (`apps/web`) replaces it. The
  stock image runs in the dev stack only until `apps/web` can stand in.
- **Backend changes stay minimal and isolated** (new packages such as
  `sprint_access/` rather than edits spread across the core), so upstream
  merges stay easy.

## Consequences

- Patches that used to be bind mounts are now commits in
  `services/kemudi-back`. See `docs/third-party/kemudi-back-changes.md`.
- The `taiga-v2` front patches (link items, clone, board fields, filter search,
  sprint access UI, related-tasks filter, move task) do not exist in Kemudi
  until `apps/web` rebuilds them. The sprint-access backend works, but has no
  UI in the stock front.
- Contributors must clone with `--recurse-submodules` to get Awak.
- `.gitattributes` forces LF line endings, because Windows checkouts with
  `core.autocrlf=true` otherwise break the shell entrypoints inside the images.
