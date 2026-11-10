/** Epics and the stories related to them. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from './client'
import { onFail, refreshLists } from './items'
import type { Id, Item, Project, UserStory } from './types'

const ALL = { headers: { 'x-disable-pagination': '1' } }

export interface Epic extends Item {
  color: string
  epics_order: number
  user_stories_counts: { total: number; progress: number }
}

export function useEpics(projectId: Id) {
  return useQuery({
    queryKey: ['epics', projectId],
    queryFn: async () =>
      (
        await api.get<Epic[]>('/epics', {
          params: { project: projectId },
          ...ALL,
        })
      ).data.sort((a, b) => a.epics_order - b.epics_order),
  })
}

export function useEpicStories(projectId: Id, epicId: Id, enabled = true) {
  return useQuery({
    queryKey: ['epic-stories', projectId, epicId],
    enabled,
    queryFn: async () =>
      (
        await api.get<UserStory[]>('/userstories', {
          params: { project: projectId, epic: epicId },
          ...ALL,
        })
      ).data,
  })
}

export function useCreateEpic(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      subject: string
      color: string
      description?: string
    }) =>
      (await api.post<Epic>('/epics', { project: project.id, ...input })).data,
    onSuccess: (epic) => toast.success(`Epic #${epic.ref} created`),
    onError: onFail,
    onSettled: () => refreshLists(qc),
  })
}

/** Link, unlink, or create-and-link stories under an epic. */
export function useEpicLinks(project: Project) {
  const qc = useQueryClient()
  const settle = () => {
    refreshLists(qc)
    qc.invalidateQueries({ queryKey: ['item', project.id] })
  }
  type Pair = { epicId: Id; storyId: Id }
  const link = useMutation({
    mutationFn: ({ epicId, storyId }: Pair) =>
      api.post(`/epics/${epicId}/related_userstories`, {
        epic: epicId,
        user_story: storyId,
      }),
    onError: onFail,
    onSettled: settle,
  })
  const unlink = useMutation({
    mutationFn: ({ epicId, storyId }: Pair) =>
      api.delete(`/epics/${epicId}/related_userstories/${storyId}`),
    onError: onFail,
    onSettled: settle,
  })
  const create = useMutation({
    mutationFn: ({ epicId, text }: { epicId: Id; text: string }) =>
      api.post(`/epics/${epicId}/related_userstories/bulk_create`, {
        project_id: project.id,
        bulk_userstories: text,
      }),
    onError: onFail,
    onSettled: settle,
  })
  return { link, unlink, create }
}
