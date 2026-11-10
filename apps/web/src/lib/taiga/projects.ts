/** Creating, duplicating and discovering projects; likes and watches. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { onFail } from './items'
import type { Id, Project, ProjectSummary } from './types'

export interface ProjectTemplate {
  id: Id
  name: string
  slug: string
  description: string
}

export type DiscoverProject = ProjectSummary & {
  is_fan: boolean
  is_watcher: boolean
  total_fans: number
  total_watchers: number
  tags: string[] | null
}

export function useProjectTemplates() {
  return useQuery({
    queryKey: ['project-templates'],
    staleTime: Infinity,
    queryFn: async () =>
      (await api.get<ProjectTemplate[]>('/project-templates')).data,
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      name: string
      description: string
      creation_template: Id
      is_private: boolean
    }) => (await api.post<Project>('/projects', input)).data,
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export function useDuplicateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      project: { id: Id }
      name: string
      description: string
      is_private: boolean
      users: Id[]
    }) =>
      (
        await api.post<Project>(`/projects/${input.project.id}/duplicate`, {
          name: input.name,
          description: input.description,
          is_private: input.is_private,
          users: input.users.map((id) => ({ id })),
        })
      ).data,
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export function useDiscover(q: string) {
  return useQuery({
    queryKey: ['discover', q],
    queryFn: async () =>
      (
        await api.get<DiscoverProject[]>('/projects', {
          params: {
            discover_mode: true,
            order_by: '-total_fans',
            ...(q ? { q } : {}),
          },
          headers: { 'x-disable-pagination': '1' },
        })
      ).data,
  })
}

/** Like (fan) or watch a project; toggles. */
export function useProjectToggle(action: 'like' | 'watch') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: DiscoverProject) => {
      const on = action === 'like' ? p.is_fan : p.is_watcher
      const verb =
        action === 'like' ? (on ? 'unlike' : 'like') : on ? 'unwatch' : 'watch'
      return api.post(`/projects/${p.id}/${verb}`)
    },
    onError: onFail,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['discover'] })
      qc.invalidateQueries({ queryKey: ['project'] })
    },
  })
}
