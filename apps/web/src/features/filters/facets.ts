import i18n from '@/i18n'
import type { Project, Status, UserStory } from '@/lib/taiga/types'
import type { Facet, FacetOption } from './apply'

/**
 * Facets shared by stories, tasks and issues. `0` means "nobody" / "none".
 * Labels are getters so they follow the UI language when read at render.
 */
export function statusFacet<T extends { status: number }>(
  statuses: Status[]
): Facet<T> {
  return {
    key: 'status',
    get label() {
      return i18n.t('common:terms.status')
    },
    options: [...statuses]
      .sort((a, b) => a.order - b.order)
      .map((s) => ({ value: s.id, label: s.name, color: s.color })),
    values: (item) => [item.status],
  }
}

export function assigneeFacet<
  T extends { assigned_to: number | null; assigned_users?: number[] },
>(project: Project): Facet<T> {
  const options: FacetOption[] = [
    {
      value: 0,
      get label() {
        return i18n.t('common:status.unassigned')
      },
    },
    ...project.members.map((m) => ({
      value: m.id,
      label: m.full_name_display,
    })),
  ]
  return {
    key: 'assignee',
    get label() {
      return i18n.t('common:terms.assignee')
    },
    options,
    values: (item) => {
      const ids = item.assigned_users?.length
        ? item.assigned_users
        : item.assigned_to
          ? [item.assigned_to]
          : []
      return ids.length ? ids : [0]
    },
  }
}

export function tagFacet<T extends { tags: [string, string | null][] }>(
  project: Project,
  items: T[]
): Facet<T> {
  const names = new Set<string>(Object.keys(project.tags_colors))
  for (const item of items) for (const [t] of item.tags) names.add(t)
  return {
    key: 'tags',
    get label() {
      return i18n.t('common:terms.tags')
    },
    options: [...names]
      .sort()
      .map((t) => ({ value: t, label: t, color: project.tags_colors[t] })),
    values: (item) => item.tags.map(([t]) => t),
  }
}

export function epicFacet(stories: UserStory[]): Facet<UserStory> {
  const epics = new Map<number, FacetOption>()
  for (const s of stories)
    for (const e of s.epics ?? [])
      epics.set(e.id, {
        value: e.id,
        label: `#${e.ref} ${e.subject}`,
        color: e.color,
      })
  return {
    key: 'epic',
    get label() {
      return i18n.t('common:terms.epic', { count: 1 })
    },
    options: [
      {
        value: 0,
        get label() {
          return i18n.t('board:filters.noEpic')
        },
      },
      ...epics.values(),
    ],
    values: (s) => (s.epics?.length ? s.epics.map((e) => e.id) : [0]),
  }
}
