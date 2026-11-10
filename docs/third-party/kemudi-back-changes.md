# Changes to taiga-back in services/kemudi-back

Base: taiga-back 6.10.2 (MPL-2.0). Every file below is a modified MPL-2.0
file and stays under MPL-2.0.

| File | Change |
|---|---|
| `taiga/projects/userstories/api.py` | `get_queryset()` ignores a non-numeric `?epic=` (e.g. `null`) instead of raising a 500 on `/userstories` and `/userstories/by_ref`. |
| `taiga/importers/jira/{agile,api,common,normal,tasks}.py` | Jira Cloud compatibility: `accountId` instead of the legacy `key`/`name` user fields, and `nextPageToken` pagination. |
| `sprint_access/__init__.py` (new) | Per-role sprint access. Configuration is stored as `sprint:<id>` entries in `Role.permissions`, so there is no schema change. |
| `taiga/wsgi.py` | Imports `sprint_access` after Django setup. |

These originate from the Aegis `taiga-v2` deployment, where they were
bind-mounted over taiga-back 6.9.0. Upstream changed only
`userstories/api.py` between 6.9.0 and 6.10.2, and that change was merged with
`patch` without conflicts.

To list them from git:

```sh
git diff upstream/taiga-back/6.10.2 HEAD --stat -- services/kemudi-back
```
