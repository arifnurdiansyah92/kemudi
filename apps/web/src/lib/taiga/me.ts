/** The signed-in user's work across projects, and their notifications. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@/stores/auth-store'
import { api } from './client'
import { onFail } from './items'
import type { Id, Item, ItemKind } from './types'

const ALL = { headers: { 'x-disable-pagination': '1' } }

export type MyItem = Item & {
  kind: ItemKind
  project_extra_info: { id: Id; name: string; slug: string }
}

const ENDPOINTS: [ItemKind, string][] = [
  ['userstory', 'userstories'],
  ['task', 'tasks'],
  ['issue', 'issues'],
]

/** Open stories, tasks and issues assigned to me, or that I watch. */
export function useMyItems(filter: 'assigned' | 'watching') {
  const me = useAuthStore((s) => s.session?.user.id)
  return useQuery({
    queryKey: ['my-items', filter, me],
    enabled: !!me,
    queryFn: async () => {
      const lists = await Promise.all(
        ENDPOINTS.map(async ([kind, endpoint]) => {
          const params: Record<string, unknown> = { status__is_closed: false }
          if (filter === 'watching') params.watchers = me
          else if (kind === 'userstory') params.assigned_users = me
          else params.assigned_to = me
          const { data } = await api.get<MyItem[]>(`/${endpoint}`, {
            params,
            ...ALL,
          })
          return data.map((item) => ({ ...item, kind }))
        })
      )
      return lists
        .flat()
        .sort((a, b) => b.modified_date.localeCompare(a.modified_date))
    },
  })
}

export interface WebNotification {
  id: Id
  event_type: 1 | 2 | 3 | 4 | 5 | 6
  created: string
  read: string | null
  data: {
    project?: { id: Id; slug: string; name: string }
    user?: { id: Id; name: string; photo: string | null; username: string }
    obj?: {
      id: Id
      ref: number | null
      subject: string | null
      content_type: string
    }
  }
}

export function useNotifications() {
  return useQuery({
    queryKey: ['notifications'],
    // No push channel for these yet; check once a minute.
    refetchInterval: 60_000,
    queryFn: async () =>
      (
        await api.get<{ objects: WebNotification[]; total: number }>(
          '/web-notifications',
          { params: { page_size: 30 } }
        )
      ).data,
  })
}

export function useMarkNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (n?: WebNotification) =>
      n
        ? api.patch(`/web-notifications/${n.id}/set-as-read`)
        : api.post('/web-notifications/set-as-read'),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
}
