/** Sprints (milestones), their taskboard, stats and bulk creation. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from './client'
import { onFail, refreshLists } from './items'
import type { Id, Milestone, Project, Task } from './types'

const ALL = { headers: { 'x-disable-pagination': '1' } }

export interface SprintStats {
  name: string
  estimated_start: string
  estimated_finish: string
  total_points: Record<string, number>
  total_userstories: number
  completed_userstories: number
  total_tasks: number
  completed_tasks: number
  iocaine_doses: number
  days: { day: string; open_points: number; optimal_points: number }[]
}

export function useSprint(id: Id) {
  return useQuery({
    queryKey: ['sprint', id],
    queryFn: async () => (await api.get<Milestone>(`/milestones/${id}`)).data,
  })
}

export function useClosedSprints(projectId: Id, enabled = true) {
  return useQuery({
    queryKey: ['milestones', projectId, 'closed'],
    enabled,
    queryFn: async () =>
      (
        await api.get<Milestone[]>('/milestones', {
          params: { project: projectId, closed: true },
          ...ALL,
        })
      ).data,
  })
}

export function useSprintTasks(projectId: Id, sprintId: Id) {
  return useQuery({
    queryKey: ['sprint-tasks', projectId, sprintId],
    queryFn: async () =>
      (
        await api.get<Task[]>('/tasks', {
          params: { project: projectId, milestone: sprintId },
          ...ALL,
        })
      ).data,
  })
}

export function useSprintStats(id: Id) {
  return useQuery({
    queryKey: ['sprint-stats', id],
    queryFn: async () =>
      (await api.get<SprintStats>(`/milestones/${id}/stats`)).data,
  })
}

function useRefreshSprint(id?: Id) {
  const qc = useQueryClient()
  return () => {
    refreshLists(qc)
    if (id) {
      qc.invalidateQueries({ queryKey: ['sprint', id] })
      qc.invalidateQueries({ queryKey: ['sprint-stats', id] })
    }
  }
}

export function useUpdateSprint(id: Id) {
  const refresh = useRefreshSprint(id)
  return useMutation({
    mutationFn: (
      patch: Partial<
        Pick<
          Milestone,
          'name' | 'estimated_start' | 'estimated_finish' | 'closed'
        >
      >
    ) => api.patch<Milestone>(`/milestones/${id}`, patch),
    onError: onFail,
    onSettled: refresh,
  })
}

export function useDeleteSprint() {
  const refresh = useRefreshSprint()
  return useMutation({
    mutationFn: (sprint: Milestone) => api.delete(`/milestones/${sprint.id}`),
    onSuccess: (_d, sprint) => toast.success(`${sprint.name} deleted`),
    onError: onFail,
    onSettled: refresh,
  })
}

/**
 * Drops a task into a taskboard cell: PATCH its status and story when they
 * change, then store the cell's new order.
 */
export function useMoveTask(project: Project, sprintId: Id) {
  const qc = useQueryClient()
  const key = ['sprint-tasks', project.id, sprintId]
  return useMutation({
    mutationFn: async (input: {
      task: Task
      statusId: Id
      storyId: Id | null
      cell: Id[]
    }) => {
      const { task, statusId, storyId, cell } = input
      if (task.status !== statusId || task.user_story !== storyId)
        await api.patch(`/tasks/${task.id}`, {
          status: statusId,
          user_story: storyId,
          version: task.version,
        })
      await api.post('/tasks/bulk_update_taskboard_order', {
        project_id: project.id,
        milestone_id: sprintId,
        status_id: statusId,
        bulk_tasks: cell.map((task_id, order) => ({ task_id, order })),
      })
    },
    onMutate: async ({ task, statusId, storyId, cell }) => {
      await qc.cancelQueries({ queryKey: key })
      const status = project.task_statuses.find((s) => s.id === statusId)
      qc.setQueryData<Task[]>(key, (list) =>
        list?.map((t) => {
          const order = cell.indexOf(t.id)
          if (t.id === task.id)
            return {
              ...t,
              status: statusId,
              user_story: storyId,
              taskboard_order: order,
              is_closed: status?.is_closed ?? t.is_closed,
              status_extra_info: status
                ? {
                    name: status.name,
                    color: status.color,
                    is_closed: status.is_closed,
                  }
                : t.status_extra_info,
            }
          return order >= 0 ? { ...t, taskboard_order: order } : t
        })
      )
    },
    onError: onFail,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: key })
      qc.invalidateQueries({ queryKey: ['sprint-stats', sprintId] })
      qc.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

/** One task per line, under a story (or none) in a sprint. */
export function useBulkCreateTasks(project: Project, sprintId: Id) {
  const refresh = useRefreshSprint(sprintId)
  return useMutation({
    mutationFn: (input: { storyId: Id | null; statusId?: Id; text: string }) =>
      api.post('/tasks/bulk_create', {
        project_id: project.id,
        milestone_id: sprintId,
        us_id: input.storyId ?? undefined,
        status_id: input.statusId,
        bulk_tasks: input.text,
      }),
    onError: onFail,
    onSettled: refresh,
  })
}

/** One story per line, into the backlog. */
export function useBulkCreateStories(project: Project) {
  const refresh = useRefreshSprint()
  return useMutation({
    mutationFn: (input: { text: string; statusId?: Id }) =>
      api.post('/userstories/bulk_create', {
        project_id: project.id,
        status_id: input.statusId,
        bulk_stories: input.text,
      }),
    onError: onFail,
    onSettled: refresh,
  })
}

interface ProjectStatsData {
  total_points: number | null
  closed_points: number
  defined_points: number
  assigned_points: number
  speed: number
  total_milestones: number | null
}

/** Points closed, defined and assigned, and the team's speed per sprint. */
export function useProjectStats(projectId: Id) {
  return useQuery({
    queryKey: ['project-stats', projectId],
    queryFn: async () =>
      (await api.get<ProjectStatsData>(`/projects/${projectId}/stats`)).data,
  })
}
