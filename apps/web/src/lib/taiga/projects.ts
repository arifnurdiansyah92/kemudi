/** Creating and duplicating projects. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { onFail } from './items'
import type { Id, Project } from './types'

interface ProjectTemplate {
  id: Id
  name: string
  slug: string
  description: string
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
    }) =>
      // Kemudi projects are never public: vendor work stays inside the vendor.
      (await api.post<Project>('/projects', { ...input, is_private: true }))
        .data,
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
      users: Id[]
    }) =>
      (
        await api.post<Project>(`/projects/${input.project.id}/duplicate`, {
          name: input.name,
          description: input.description,
          is_private: true,
          users: input.users.map((id) => ({ id })),
        })
      ).data,
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })
}
