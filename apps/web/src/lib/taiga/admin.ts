/** Project settings: details, logo, modules, ownership, deletion. */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, apiErrorMessage } from './client'
import { onFail } from './items'
import type { Id, Project } from './types'

/** Refetch the project everywhere it is cached (by slug and in lists). */
export function useRefreshProject() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['project'] })
    qc.invalidateQueries({ queryKey: ['projects'] })
  }
}

export function useUpdateProject(project: Project) {
  const refresh = useRefreshProject()
  return useMutation({
    mutationFn: async (patch: Record<string, unknown>) =>
      (await api.patch<Project>(`/projects/${project.id}`, patch)).data,
    onSuccess: () => toast.success('Project settings saved'),
    onError: onFail,
    onSettled: refresh,
  })
}

export function useProjectLogo(project: Project) {
  const refresh = useRefreshProject()
  const change = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('logo', file)
      return api.post(`/projects/${project.id}/change_logo`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onError: (e) =>
      toast.error(
        apiErrorMessage(e, 'That image could not be used as a logo.')
      ),
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: () => api.post(`/projects/${project.id}/remove_logo`),
    onError: onFail,
    onSettled: refresh,
  })
  return { change, remove }
}

export function useDeleteProject(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete(`/projects/${project.id}`),
    onSuccess: () => {
      toast.success(`${project.name} deleted`)
      qc.removeQueries({ queryKey: ['project', project.slug] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: onFail,
  })
}

/** Emails the chosen member a link to accept ownership. */
export function useStartTransfer(project: Project) {
  return useMutation({
    mutationFn: (input: { user: Id; reason: string }) =>
      api.post(`/projects/${project.id}/transfer_start`, input),
    onSuccess: () =>
      toast.success(
        'Ownership offered. They get an email to accept or decline.'
      ),
    onError: onFail,
  })
}
