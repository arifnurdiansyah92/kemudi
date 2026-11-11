/** Issues: the list, creation, and promoting issues or tasks to stories. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import i18n from '@/i18n'
import { toast } from 'sonner'
import { api } from './client'
import { KINDS, onFail, refreshLists } from './items'
import type { Id, Item, ItemKind, Project } from './types'

export function useIssues(projectId: Id) {
  return useQuery({
    queryKey: ['issues', projectId],
    queryFn: async () =>
      (
        await api.get<Item[]>('/issues', {
          params: { project: projectId },
          headers: { 'x-disable-pagination': '1' },
        })
      ).data,
  })
}

export type NewIssue = {
  subject: string
  description?: string
  type?: Id | null
  severity?: Id | null
  priority?: Id | null
  assigned_to?: Id | null
  milestone?: Id | null
}

export function useCreateIssue(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: NewIssue) =>
      (await api.post<Item>('/issues', { project: project.id, ...input })).data,
    onSuccess: (issue) =>
      toast.success(i18n.t('shell:toast.issueCreated', { ref: issue.ref })),
    onError: onFail,
    onSettled: () => refreshLists(qc),
  })
}

export function useBulkCreateIssues(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text: string) =>
      api.post('/issues/bulk_create', {
        project_id: project.id,
        bulk_issues: text,
      }),
    onError: onFail,
    onSettled: () => refreshLists(qc),
  })
}

/**
 * Turns an issue or task into a story. kemudi-back answers with the new
 * stories' refs; a promoted task is deleted.
 */
export function usePromote(project: Project, kind: ItemKind) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (item: Item) =>
      (
        await api.post<number[]>(
          `/${KINDS[kind].endpoint}/${item.id}/promote_to_user_story`,
          { project_id: project.id }
        )
      ).data,
    onError: onFail,
    onSettled: () => refreshLists(qc),
  })
}
