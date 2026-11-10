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
- [ ] Members: invite, change role, remove
- [ ] Roles and permissions
- [ ] Attributes: statuses, points, priorities, severities, types, swimlanes, due dates
- [ ] Custom fields
- [ ] Tags colours
- [ ] Webhooks
- [ ] Export, import, CSV links
- [x] Transfer ownership (offer), delete project, duplicate

## Account

- [x] Sign in, forgot and change password
- [ ] Sign up, accept invitation
- [ ] Profile: name, bio, photo, language, timezone
- [ ] Change password, email, delete account
- [ ] Notification settings per project
- [ ] Application tokens

## Importers

- [ ] Jira, Trello, GitHub, Asana

## Aegis additions

- [ ] Sprint access per role (`sprint_access` backend)
