# apps/web: Taiga feature coverage

What taiga-front does, and whether `apps/web` does it yet. Each item lands as
its own small commit. Source of truth for the API: `services/kemudi-back/taiga/routers.py`.

## Work items (stories, tasks, issues, epics)

- [x] Story detail: subject, status, assignee, description, tasks, comments
- [x] One detail sheet for all item types, opened by `?ref=` (resolver)
- [x] Tags: add, remove
- [x] Blocked flag with reason
- [x] Due date
- [x] Watch / unwatch, watchers list; vote (issues, epics)
- [x] Attachments: upload, list, delete
- [x] Custom attributes (per item type)
- [x] Activity history
- [x] Story points per role
- [x] Multiple assignees (stories)
- [x] Delete item
- [x] Client / team requirement flags (stories)
- [x] Edit and delete own comments

## Scrum

- [x] Backlog list, reorder, quick add, move to sprint
- [x] Open sprints panel, new sprint
- [x] Bulk create stories (one per line)
- [x] Backlog search and filters (status, assignee, tags, epic)
- [x] Edit, close and delete sprints; closed sprints
- [x] Sprint taskboard (stories by task status, drag tasks)
- [x] Sprint burndown and stats
- [x] Project burndown / stats in backlog

## Kanban

- [x] Columns by status, drag within and across, WIP count, quick add
- [x] Swimlanes
- [x] Fold columns, archived status
- [x] Search and filters

## Issues

- [x] Issues list with sort, search, filters
- [x] Create issue, bulk create
- [x] Type, severity, priority
- [x] Promote issue to story

## Epics

- [x] Epics list with progress
- [x] Create epic, colour
- [x] Related stories (link, unlink, create)

## Wiki

- [x] Pages: view, create, edit, delete
- [x] Wiki links (sidebar bookmarks)

## Links

- [x] Old taiga-front URLs (emails, #ref mentions, wiki links) open the matching Kemudi screen

## Team and activity

- [x] Team page with members and roles
- [x] Project timeline (activity)
- [x] Home: working on, watching
- [x] Notifications (web notifications)
- [x] Global search
- [x] Live updates (taiga-events websocket)

## Projects

- [x] Projects list
- [x] Create project (template); duplicate is in project settings
- [x] Discover public projects, like and watch projects
- [x] Leave project

## Project admin

- [x] Details: name, description, logo, privacy, planned sprints and points, looking for people
- [x] Modules on/off, videoconference
- [x] Members: invite (several at once, with a note), change role, admin flag, remove, resend and cancel invitations
- [x] Roles and permissions (per-role matrix, points roles, public and anonymous access)
- [x] Attributes: statuses, points, priorities, severities, types, swimlanes, due dates
- [x] Custom fields (per item kind, all field types, dropdown choices)
- [x] Tags: colour, rename, merge, delete
- [x] Webhooks (create, edit, test, delivery log, resend)
- [x] Export, import (on the new project page), CSV feed links
- [x] Transfer ownership (offer), delete project, duplicate

## Account

- [x] Sign in, forgot and change password
- [x] Sign up (when the server allows it), accept invitation (new or existing account), accept or decline project ownership
- [x] Profile: name, username, bio, photo, language, timezone
- [x] Change password, email (with confirm link), delete account (also from the emailed link)
- [x] Notification settings per project (email level, bell)
- [x] Connected apps (application tokens): list and revoke

- [x] Public profile: activity, watching, liked projects, votes, contacts

## Importers

- [x] Jira, Trello, GitHub, Asana: connect, pick a project, match people, import. Not exercised end to end here: each needs the server's API credentials (`ENABLE_*_IMPORTER`), and without them the page says so.

## Aegis additions

- [x] Sprint access per role (`sprint_access` backend), in project settings

## Second pass (found by comparing with taiga-front)

- [x] Integrations: GitHub, GitLab, Bitbucket and Gogs commit hooks (project settings)
- [x] Watchers: see and change who watches an item
- [x] Contact the project (contact form to admins)
- [x] Wiki page history
- [x] Mentions: @people and #refs suggested while typing comments and descriptions
- [x] Saved filters on backlog, kanban and issues
- [x] Backlog: drag stories into a sprint; forecast of what fits the next sprint
- [x] Kanban: card density (zoom)
- [ ] Projects list: reorder your projects
- [x] Due date reason; epic client and team requirement flags
