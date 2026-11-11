/** Turns Taiga history diffs into short sentences. */
import i18n from '@/i18n'

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

/**
 * Taiga also sends rendered copies of some fields (`blocked_note_html`,
 * `blocked_note_diff`): HTML meant for its own front end. The plain field
 * carries the same change, so only `description_diff` is shown.
 */
export function visibleKey(key: string) {
  if (HIDDEN.has(key)) return false
  if (key.endsWith('_html')) return false
  if (key.endsWith('_diff') && key !== 'description_diff') return false
  return true
}

/** Diff keys with a translated name; others fall back to the raw key. */
const FIELDS = [
  'assigned_to',
  'assigned_users',
  'milestone',
  'is_blocked',
  'blocked_note',
  'due_date',
  'due_date_reason',
  'description_diff',
  'client_requirement',
  'team_requirement',
  'user_story',
  'custom_attributes',
  'subject',
  'status',
  'tags',
  'type',
  'priority',
  'severity',
  'watchers',
  'color',
  'points',
] as const
type Field = (typeof FIELDS)[number]

function isField(key: string): key is Field {
  return (FIELDS as readonly string[]).includes(key)
}

function fieldLabel(key: string) {
  return isField(key)
    ? i18n.t(`item:history.field.${key}`)
    : key.replace(/_/g, ' ')
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '')
    return i18n.t('item:history.none')
  if (typeof value === 'boolean')
    return value ? i18n.t('item:history.yes') : i18n.t('item:history.no')
  if (Array.isArray(value))
    return value.length
      ? value.map(show).join(', ')
      : i18n.t('item:history.none')
  return String(value)
}

/** One readable line per changed field. Call at render time. */
export function describe(key: string, value: unknown): string {
  if (key === 'description_diff')
    return i18n.t('item:history.updatedDescription')
  if (key === 'attachments') {
    const v = value as { new?: unknown[]; deleted?: unknown[] }
    const parts = []
    if (v.new?.length)
      parts.push(i18n.t('item:history.attached', { count: v.new.length }))
    if (v.deleted?.length)
      parts.push(i18n.t('item:history.removed', { count: v.deleted.length }))
    return parts.join(', ') || i18n.t('item:history.changedAttachments')
  }
  if (key === 'points' && value && typeof value === 'object') {
    return Object.entries(value as Record<string, [unknown, unknown]>)
      .map(([role, [from, to]]) =>
        i18n.t('item:history.setPoints', {
          role,
          from: show(from),
          to: show(to),
        })
      )
      .join('; ')
  }
  const field = fieldLabel(key)
  if (Array.isArray(value) && value.length === 2)
    return i18n.t('item:history.changedFromTo', {
      field,
      from: show(value[0]),
      to: show(value[1]),
    })
  return i18n.t('item:history.changed', { field })
}
