/** Turns Taiga history diffs into short sentences. */

const HIDDEN = new Set([
  'kanban_order',
  'backlog_order',
  'sprint_order',
  'taskboard_order',
  'us_order',
  'epics_order',
  'finish_date',
  'version',
])

export function visibleKey(key: string) {
  return !HIDDEN.has(key)
}

const LABELS: Record<string, string> = {
  assigned_to: 'assignee',
  assigned_users: 'assignees',
  milestone: 'sprint',
  is_blocked: 'blocked',
  blocked_note: 'blocked reason',
  due_date: 'due date',
  description_diff: 'description',
  client_requirement: 'client requirement',
  team_requirement: 'team requirement',
  is_iocaine: 'iocaine',
  user_story: 'story',
  custom_attributes: 'custom fields',
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'none'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (Array.isArray(value))
    return value.length ? value.map(show).join(', ') : 'none'
  return String(value)
}

/** One readable line per changed field. */
export function describe(key: string, value: unknown): string {
  const label = LABELS[key] ?? key.replace(/_/g, ' ')
  if (key === 'description_diff') return 'updated the description'
  if (key === 'attachments') {
    const v = value as { new?: unknown[]; deleted?: unknown[] }
    const parts = []
    if (v.new?.length) parts.push(`attached ${v.new.length} file(s)`)
    if (v.deleted?.length) parts.push(`removed ${v.deleted.length} file(s)`)
    return parts.join(', ') || 'changed attachments'
  }
  if (key === 'points' && value && typeof value === 'object') {
    return Object.entries(value as Record<string, [unknown, unknown]>)
      .map(
        ([role, [from, to]]) => `set ${role} points ${show(from)} → ${show(to)}`
      )
      .join('; ')
  }
  if (Array.isArray(value) && value.length === 2)
    return `changed ${label} from ${show(value[0])} to ${show(value[1])}`
  return `changed ${label}`
}
