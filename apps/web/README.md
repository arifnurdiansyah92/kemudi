# apps/web

The Kemudi web UI. React 19, Vite, TypeScript, TanStack Router and Query,
Tailwind CSS 4 and shadcn/ui, started from
[shadcn-admin](https://github.com/satnaing/shadcn-admin) 2.2.1 (MIT, see
`LICENSE.shadcn-admin`). It talks to `services/kemudi-back` over the Taiga
REST API (`/api/v1`).

## What it covers

| Screen                                     | Route                                                      | Notes                                                                                                          |
| ------------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Sign in, forgot password, set new password | `/sign-in`, `/forgot-password`, `/change-password/<token>` | The reset email from kemudi-back links to the last one.                                                        |
| Projects                                   | `/`                                                        | Projects you are a member of.                                                                                  |
| Backlog                                    | `/p/<slug>/backlog`                                        | Drag to reorder, quick add, status and assignee menus, move to sprint, open sprints with progress, new sprint. |
| Kanban                                     | `/p/<slug>/kanban`                                         | Drag across and within columns, WIP counts, quick add per column.                                              |
| Story sheet                                | `?story=<ref>` on either view                              | Subject, status, assignee, description (Markdown), tasks, comments.                                            |
| Appearance                                 | `/settings/appearance`                                     | Font and theme.                                                                                                |

Not built yet, still on the stock UI at <http://localhost:9101>: sprint
taskboard, issues, epics, wiki, project admin, user profile, and the taiga-v2
patches (link items, clone, board fields, filter search, sprint access, move
task). Views respect the project's module switches: kanban redirects to the
backlog when kanban is off, and the reverse.

## Develop

Needs Node 22.12+ (see `.node-version`) and pnpm 10, plus the dev stack from
the repo root running on <http://localhost:9100>.

```sh
pnpm install
pnpm dev          # http://localhost:5173, proxies /api, /media, /events to :9100
pnpm typecheck
pnpm lint
pnpm test         # Vitest in headless Chromium; first run: pnpm test:browser:install
pnpm build
```

Set `KEMUDI_DEV_GATEWAY` to proxy to another stack, or `VITE_API_URL` if the
API is not on the same origin in production. See `.env.example`.

## Layout

```
src/
├── lib/taiga/        API client (auth, token refresh), types, query hooks
├── stores/           session (token, refresh token, user) in localStorage
├── features/
│   ├── auth/         sign-in, forgot and change password
│   ├── projects/     projects list
│   ├── project/      useProject(), permissions, story sheet URL state
│   ├── backlog/      backlog list, sprint panels, new-sprint dialog
│   ├── kanban/       board and cards
│   ├── story/        story sheet and shared parts (status, assignee, tags)
│   └── settings/     appearance
├── components/       layout shell, sidebar, command menu (Ctrl/Cmd+K), ui/
└── routes/           file routes (TanStack Router)
```

Notes for changing things:

- Every story `PATCH` sends the cached `version`. kemudi-back rejects stale
  versions, so mutations write the returned version back into the cache.
- Kanban position is not writable through `PATCH`. A move is a status
  `PATCH` (when the column changes) followed by
  `bulk_update_kanban_order`. Backlog order uses `bulk_update_backlog_order`.
- Description and comment HTML comes from kemudi-back, which sanitises it.
- Avatars without an uploaded photo show initials on the member's colour.
  There is deliberately no Gravatar fallback, so a self-hosted install sends
  nothing to third parties.

## Container

`Dockerfile` builds the app and serves `dist/` with nginx, falling back to
`index.html` for client routes. `infra/docker-compose.dev.yml` runs it as
`kemudi-web` behind the gateway.
