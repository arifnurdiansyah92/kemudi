import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'
import { api, apiErrorMessage } from './client'
import type { LoadedItem } from './items'
import type {
  Item,
  Id,
  Milestone,
  Project,
  ProjectSummary,
  Task,
  UserStory,
  UserStoryDetail,
} from './types'

const ALL = { headers: { 'x-disable-pagination': '1' } }

export const keys = {
  projects: (userId: Id) => ['projects', userId] as const,
  project: (slug: string) => ['project', slug] as const,
  stories: (projectId: Id) => ['stories', projectId] as const,
  milestones: (projectId: Id) => ['milestones', projectId] as const,
  tasks: (storyId: Id) => ['tasks', storyId] as const,
}

/* ---------- queries ---------- */

const projectsQuery = (userId: Id) =>
  queryOptions({
    queryKey: keys.projects(userId),
    queryFn: async () =>
      (
        await api.get<ProjectSummary[]>('/projects', {
          params: { member: userId, order_by: 'user_order' },
          ...ALL,
        })
      ).data,
  })

export function useProjects() {
  const userId = useAuthStore((s) => s.session?.user.id)
  return useQuery({ ...projectsQuery(userId ?? 0), enabled: !!userId })
}

export const projectQuery = (slug: string) =>
  queryOptions({
    queryKey: keys.project(slug),
    queryFn: async () =>
      (await api.get<Project>('/projects/by_slug', { params: { slug } })).data,
    staleTime: 60_000,
  })

export const storiesQuery = (projectId: Id) =>
  queryOptions({
    queryKey: keys.stories(projectId),
    queryFn: async () =>
      (
        await api.get<UserStory[]>('/userstories', {
          params: { project: projectId, status__is_archived: false },
          ...ALL,
        })
      ).data,
  })

export function useStories(projectId: Id) {
  return useQuery(storiesQuery(projectId))
}

export function useMilestones(projectId: Id) {
  return useQuery({
    queryKey: keys.milestones(projectId),
    queryFn: async () =>
      (
        await api.get<Milestone[]>('/milestones', {
          params: { project: projectId, closed: false },
          ...ALL,
        })
      ).data,
  })
}

export function useTasks(storyId: Id | undefined) {
  return useQuery({
    queryKey: keys.tasks(storyId ?? 0),
    enabled: !!storyId,
    queryFn: async () =>
      (
        await api.get<Task[]>('/tasks', {
          params: { user_story: storyId },
          ...ALL,
        })
      ).data.sort((a, b) => a.us_order - b.us_order || a.ref - b.ref),
  })
}

/* ---------- cache helpers ---------- */

function patchStoryInCache(
  qc: QueryClient,
  projectId: Id,
  storyId: Id,
  patch: Partial<UserStory>
) {
  qc.setQueryData<UserStory[]>(keys.stories(projectId), (list) =>
    list?.map((s) => (s.id === storyId ? { ...s, ...patch } : s))
  )
  // Keep the item sheet's copy (and its version) in step with the list.
  qc.setQueriesData<LoadedItem>({ queryKey: ['item', projectId] }, (d) =>
    d && d.kind === 'userstory' && d.item.id === storyId
      ? { ...d, item: { ...d.item, ...patch } as Item }
      : d
  )
}

function currentVersion(qc: QueryClient, projectId: Id, storyId: Id) {
  const fromList = qc
    .getQueryData<UserStory[]>(keys.stories(projectId))
    ?.find((s) => s.id === storyId)?.version
  const fromDetail = qc
    .getQueriesData<LoadedItem>({ queryKey: ['item', projectId] })
    .map(([, d]) => d)
    .find((d) => d?.kind === 'userstory' && d.item.id === storyId)?.item.version
  return Math.max(fromList ?? 0, fromDetail ?? 0)
}

async function patchStory(
  qc: QueryClient,
  projectId: Id,
  storyId: Id,
  patch: Record<string, unknown>
) {
  const version = currentVersion(qc, projectId, storyId)
  const { data } = await api.patch<UserStoryDetail>(`/userstories/${storyId}`, {
    ...patch,
    version,
  })
  // Write the new version back at once so a quick follow-up edit does not
  // conflict with the server's optimistic-concurrency check.
  patchStoryInCache(qc, projectId, data.id, data)
  return data
}

function onFail(error: unknown) {
  toast.error(apiErrorMessage(error, 'The change was not saved.'))
}

/* ---------- mutations ---------- */

type StoryPatch = Partial<
  Pick<
    UserStoryDetail,
    | 'subject'
    | 'status'
    | 'assigned_to'
    | 'milestone'
    | 'description'
    | 'is_blocked'
    | 'blocked_note'
    | 'tags'
  >
>

export function useUpdateStory(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: Id; patch: StoryPatch }) =>
      patchStory(qc, project.id, id, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: keys.stories(project.id) })
      const optimistic: Partial<UserStory> = { ...patch }
      if (patch.status !== undefined) {
        const status = project.us_statuses.find((s) => s.id === patch.status)
        if (status)
          optimistic.status_extra_info = {
            name: status.name,
            color: status.color,
            is_closed: status.is_closed,
          }
      }
      patchStoryInCache(qc, project.id, id, optimistic)
    },
    onSuccess: (story) => {
      patchStoryInCache(qc, project.id, story.id, story)
    },
    onError: onFail,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.stories(project.id) })
      qc.invalidateQueries({ queryKey: keys.milestones(project.id) })
    },
  })
}

export function useCreateStory(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      subject: string
      status?: Id
      milestone?: Id | null
      swimlane?: Id | null
    }) =>
      (
        await api.post<UserStory>('/userstories', {
          project: project.id,
          ...input,
        })
      ).data,
    onSuccess: (story) => {
      qc.setQueryData<UserStory[]>(keys.stories(project.id), (list) =>
        list ? [...list, story] : list
      )
    },
    onError: onFail,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.stories(project.id) })
      qc.invalidateQueries({ queryKey: keys.milestones(project.id) })
    },
  })
}

/**
 * Moves a story on the kanban board. A status change is a PATCH (which also
 * bumps the version); the position inside the column is a bulk order call,
 * because kanban_order is not writable through PATCH.
 */
export function useKanbanMove(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      story: UserStory
      statusId: Id
      /** Target swimlane; null is "no swimlane". */
      swimlaneId: Id | null
      afterId?: Id
      beforeId?: Id
      /** Where the card sits locally until the server answers. */
      optimisticOrder: number
    }) => {
      const patch: Record<string, unknown> = {}
      if (input.story.status !== input.statusId) patch.status = input.statusId
      if ((input.story.swimlane ?? null) !== input.swimlaneId)
        patch.swimlane = input.swimlaneId
      if (Object.keys(patch).length)
        await patchStory(qc, project.id, input.story.id, patch)
      await api.post('/userstories/bulk_update_kanban_order', {
        project_id: project.id,
        status_id: input.statusId,
        swimlane_id: input.swimlaneId ?? undefined,
        after_userstory_id: input.afterId,
        before_userstory_id: input.beforeId,
        bulk_userstories: [input.story.id],
      })
    },
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: keys.stories(project.id) })
      const status = project.us_statuses.find((s) => s.id === input.statusId)
      patchStoryInCache(qc, project.id, input.story.id, {
        status: input.statusId,
        swimlane: input.swimlaneId,
        kanban_order: input.optimisticOrder,
        ...(status && {
          status_extra_info: {
            name: status.name,
            color: status.color,
            is_closed: status.is_closed,
          },
        }),
      })
    },
    onError: onFail,
    onSettled: () =>
      qc.invalidateQueries({ queryKey: keys.stories(project.id) }),
  })
}

export function useBacklogReorder(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      storyId: Id
      milestoneId?: Id
      afterId?: Id
      beforeId?: Id
      optimisticOrder: number
    }) =>
      api.post('/userstories/bulk_update_backlog_order', {
        project_id: project.id,
        milestone_id: input.milestoneId,
        after_userstory_id: input.afterId,
        before_userstory_id: input.beforeId,
        bulk_userstories: [input.storyId],
      }),
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: keys.stories(project.id) })
      patchStoryInCache(qc, project.id, input.storyId, {
        backlog_order: input.optimisticOrder,
      })
    },
    onError: onFail,
    onSettled: () =>
      qc.invalidateQueries({ queryKey: keys.stories(project.id) }),
  })
}

export function useMoveToSprint(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      story,
      milestoneId,
    }: {
      story: UserStory
      milestoneId: Id | null
    }) => {
      if (milestoneId === null)
        return patchStory(qc, project.id, story.id, { milestone: null })
      await api.post('/userstories/bulk_update_milestone', {
        project_id: project.id,
        milestone_id: milestoneId,
        bulk_stories: [{ us_id: story.id, order: story.sprint_order }],
      })
    },
    onMutate: ({ story, milestoneId }) =>
      patchStoryInCache(qc, project.id, story.id, { milestone: milestoneId }),
    onError: onFail,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.stories(project.id) })
      qc.invalidateQueries({ queryKey: keys.milestones(project.id) })
    },
  })
}

export function useCreateMilestone(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      name: string
      estimated_start: string
      estimated_finish: string
    }) =>
      (
        await api.post<Milestone>('/milestones', {
          project: project.id,
          ...input,
        })
      ).data,
    onError: onFail,
    onSettled: () =>
      qc.invalidateQueries({ queryKey: keys.milestones(project.id) }),
  })
}

export function useCreateTask(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      story: { id: Id; milestone?: Id | null }
      subject: string
    }) =>
      (
        await api.post<Task>('/tasks', {
          project: project.id,
          user_story: input.story.id,
          milestone: input.story.milestone,
          subject: input.subject,
        })
      ).data,
    onSuccess: (task) =>
      qc.setQueryData<Task[]>(keys.tasks(task.user_story ?? 0), (list) =>
        list ? [...list, task] : [task]
      ),
    onError: onFail,
    onSettled: (_d, _e, { story }) =>
      qc.invalidateQueries({ queryKey: keys.tasks(story.id) }),
  })
}

export function useUpdateTask(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      task,
      patch,
    }: {
      task: Task
      patch: Partial<Pick<Task, 'status' | 'subject' | 'assigned_to'>>
    }) =>
      (
        await api.patch<Task>(`/tasks/${task.id}`, {
          ...patch,
          version: task.version,
        })
      ).data,
    onMutate: ({ task, patch }) => {
      const status = project.task_statuses.find((s) => s.id === patch.status)
      qc.setQueryData<Task[]>(keys.tasks(task.user_story ?? 0), (list) =>
        list?.map((t) =>
          t.id === task.id
            ? {
                ...t,
                ...patch,
                ...(status ? { is_closed: status.is_closed } : {}),
              }
            : t
        )
      )
    },
    onSuccess: (task) =>
      qc.setQueryData<Task[]>(keys.tasks(task.user_story ?? 0), (list) =>
        list?.map((t) => (t.id === task.id ? task : t))
      ),
    onError: onFail,
    onSettled: (_d, _e, { task }) =>
      qc.invalidateQueries({ queryKey: keys.tasks(task.user_story ?? 0) }),
  })
}
