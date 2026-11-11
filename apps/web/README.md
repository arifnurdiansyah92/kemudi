# apps/web

The Kemudi web UI. React 19, Vite, TypeScript, TanStack Router and Query,
Tailwind CSS 4 and shadcn/ui, started from
[shadcn-admin](https://github.com/satnaing/shadcn-admin) 2.2.1 (MIT, see
`LICENSE.shadcn-admin`). It talks to `services/kemudi-back` over the Taiga
REST API (`/api/v1`) and to `services/kemudi-events` over a websocket
(`/events`) for live updates.

## What it covers

Everything taiga-front does for day-to-day work and administration; the
item-by-item list is in
[docs/web-feature-coverage.md](../../docs/web-feature-coverage.md). In short:

| Area                           | Routes                                                                                                                                                                           |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Account                        | `/sign-in`, `/sign-up`, `/forgot-password`, `/invitation/<token>`, `/settings/*` (profile, password and email, notifications, connected apps, appearance), `/profile/<username>` |
| Work across projects           | `/` (working on, watching), `/projects` (create, reorder, import), `/discover`, notifications bell, Ctrl/Cmd+K search                                                            |
| A project                      | `/p/<slug>/epics`, `backlog`, `taskboard/<sprint>`, `kanban`, `issues`, `wiki/<page>`, `team`, `timeline`                                                                        |
| Any story, task, issue or epic | `?ref=<n>` on any project page opens the item sheet                                                                                                                              |
| Project admin                  | `/p/<slug>/settings/*`: general, members, roles, statuses and values, custom fields, tags, webhooks, integrations, import and export, sprint access                              |

Old taiga-front URLs (what kemudi-back puts in emails and in rendered
Markdown, such as `/project/<slug>/us/14`) redirect to the matching screen,
so `services/kemudi-back` needs no front-end URL changes. Views follow each
project's module switches.

## Languages

The UI ships in Bahasa Indonesia and English, switchable per user (ID/EN in
the user menu and Settings → Appearance; saved to the user's Taiga `lang`).
Strings live in `src/locales/<lang>/<namespace>.json`; `pnpm lint` fails on
hard-coded UI text. Rules, Indonesian style and the glossary are in
[docs/i18n.md](../../docs/i18n.md).

## Develop

Needs Node 22.12+ (see `.node-version`) and pnpm 10, plus the dev stack from
the repo root running on <http://localhost:9100>.

```sh
pnpm install
pnpm dev          # http://localhost:5173, proxies /api, /media, /events to :9100
pnpm typecheck
pnpm lint
pnpm knip         # unused files, exports and dependencies
pnpm test         # Vitest in headless Chromium; first run: pnpm test:browser:install
pnpm build
```

Set `KEMUDI_DEV_GATEWAY` to proxy to another stack, `VITE_API_URL` if the API
is not on the same origin in production, and `VITE_EVENTS_URL` for the
websocket. See `.env.example`.

## Layout

```
src/
├── lib/taiga/        API client (auth, refresh), types, and hooks per area:
│                     queries (stories), items (any item kind), sprints,
│                     issues, epics, wiki, me, account, admin, projects, live
├── lib/legacy-urls   taiga-front URL → Kemudi route mapping
├── stores/           session (token, refresh token, user) in localStorage
├── features/
│   ├── auth/         sign-in, sign-up, invitation, password and email links
│   ├── home/ projects/ profile/ notifications/ timeline/ team/
│   ├── backlog/ taskboard/ kanban/ issues/ epics/ wiki/
│   ├── item/         the item sheet and its fields, comments, attachments
│   ├── filters/      filter bar, facets, saved filters
│   ├── project-settings/  project admin pages
│   ├── settings/     your own settings
│   └── importers/    Jira, Trello, GitHub, Asana
├── components/       layout shell, sidebar, command menu, mention textarea, ui/
└── routes/           file routes (TanStack Router)
```

Notes for changing things:

- Every item `PATCH` sends the cached `version`; kemudi-back rejects stale
  versions, so mutations write the returned version back into the caches.
- Order is never part of `PATCH`: kanban, backlog, taskboard and settings
  lists use their `bulk_update_*_order` endpoints.
- Refs are unique per project across stories, tasks, issues and epics, so
  the item sheet resolves `?ref=` through `/resolver`.
- HTML from kemudi-back (descriptions, comments, wiki, diffs) is sanitised
  there; links in it that point at taiga-front routes open in-app.
- Live updates: requests carry `X-Session-Id`, so the events service does not
  echo our own changes back.
- Avatars without an uploaded photo show initials on the member's colour.
  There is deliberately no Gravatar fallback, so a self-hosted install sends
  nothing to third parties.

## Container

`Dockerfile` builds the app and serves `dist/` with nginx, falling back to
`index.html` for client routes. `infra/docker-compose.dev.yml` runs it as
`kemudi-web` behind the gateway.
