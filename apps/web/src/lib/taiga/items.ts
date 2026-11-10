/**
 * Hooks shared by every work item kind: stories, tasks, issues and epics.
 * Taiga gives them the same shape and parallel endpoints, so the detail
 * sheet works on any of them through `KINDS`.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, apiErrorMessage } from './client'
import type {
  Attachment,
  CustomAttribute,
  CustomAttributeValues,
  HistoryChange,
  Id,
  Item,
  ItemKind,
  Project,
  ResolvedRef,
  Status,
  UserStory,
} from './types'

type KindConfig = {
  label: string
  endpoint: string
  history: string
  resolverKey: keyof ResolvedRef
  statuses: (p: Project) => Status[]
  perm: { modify: string; delete: string; comment: string; add: string }
  voting: boolean
}

export const KINDS: Record<ItemKind, KindConfig> = {
  userstory: {
    label: 'Story',
    endpoint: 'userstories',
    history: 'userstory',
    resolverKey: 'us',
    statuses: (p) => p.us_statuses,
    perm: {
      modify: 'modify_us',
      delete: 'delete_us',
      comment: 'comment_us',
      add: 'add_us',
    },
    voting: false,
  },
  task: {
    label: 'Task',
    endpoint: 'tasks',
    history: 'task',
    resolverKey: 'task',
    statuses: (p) => p.task_statuses,
    perm: {
      modify: 'modify_task',
      delete: 'delete_task',
      comment: 'comment_task',
      add: 'add_task',
    },
    voting: false,
  },
  issue: {
    label: 'Issue',
    endpoint: 'issues',
    history: 'issue',
    resolverKey: 'issue',
    statuses: (p) => p.issue_statuses,
    perm: {
      modify: 'modify_issue',
      delete: 'delete_issue',
      comment: 'comment_issue',
      add: 'add_issue',
    },
    voting: true,
  },
  epic: {
    label: 'Epic',
    endpoint: 'epics',
    history: 'epic',
    resolverKey: 'epic',
    statuses: (p) => p.epic_statuses,
    perm: {
      modify: 'modify_epic',
      delete: 'delete_epic',
      comment: 'comment_epic',
      add: 'add_epic',
    },
    voting: true,
  },
}

const ALL = { headers: { 'x-disable-pagination': '1' } }

export type LoadedItem = { kind: ItemKind; item: Item }

export const itemKey = (projectId: Id, ref: number) =>
  ['item', projectId, ref] as const

/** Lists that show items; refreshed after any item change. */
const LIST_PREFIXES = [
  'stories',
  'tasks',
  'sprint-tasks',
  'issues',
  'epics',
  'epic-stories',
  'milestones',
]

export function refreshLists(qc: QueryClient) {
  for (const prefix of LIST_PREFIXES)
    qc.invalidateQueries({ queryKey: [prefix] })
}

export function onFail(error: unknown) {
  toast.error(apiErrorMessage(error, 'The change was not saved.'))
}

/* ---------- loading ---------- */

/** Loads whatever item `ref` points at in this project. */
export function useRefItem(project: Project, ref: number | undefined) {
  // project.slug is a function of project.id, so the id keys it fully.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  return useQuery({
    queryKey: itemKey(project.id, ref ?? 0),
    enabled: ref !== undefined,
    queryFn: async (): Promise<LoadedItem> => {
      const { data: resolved } = await api.get<ResolvedRef>('/resolver', {
        params: { project: project.slug, ref },
      })
      const kind = (Object.keys(KINDS) as ItemKind[]).find(
        (k) => resolved[KINDS[k].resolverKey] !== undefined
      )
      if (!kind) throw new Error(`#${ref} is not a story, task, issue or epic`)
      const { data: item } = await api.get<Item>(
        `/${KINDS[kind].endpoint}/by_ref`,
        { params: { project: project.id, ref } }
      )
      return { kind, item }
    },
  })
}

/* ---------- writing ---------- */

/** Highest version any cache has seen for this item. */
function latestVersion(qc: QueryClient, project: Id, item: Item) {
  const detail = qc.getQueryData<LoadedItem>(itemKey(project, item.ref))
  const fromStories = qc
    .getQueryData<UserStory[]>(['stories', project])
    ?.find((s) => s.ref === item.ref)?.version
  return Math.max(item.version, detail?.item.version ?? 0, fromStories ?? 0)
}

function writeBack(qc: QueryClient, project: Id, kind: ItemKind, item: Item) {
  qc.setQueryData<LoadedItem>(itemKey(project, item.ref), { kind, item })
  if (kind === 'userstory')
    qc.setQueryData<UserStory[]>(['stories', project], (list) =>
      list?.map((s) =>
        s.id === item.id ? ({ ...s, ...item } as UserStory) : s
      )
    )
}

export async function patchItem(
  qc: QueryClient,
  project: Id,
  kind: ItemKind,
  item: Item,
  patch: Record<string, unknown>
) {
  const { data } = await api.patch<Item>(
    `/${KINDS[kind].endpoint}/${item.id}`,
    { ...patch, version: latestVersion(qc, project, item) }
  )
  writeBack(qc, project, kind, data)
  return data
}

export function useUpdateItem(project: Project, kind: ItemKind) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      item,
      patch,
    }: {
      item: Item
      patch: Record<string, unknown>
    }) => patchItem(qc, project.id, kind, item, patch),
    onMutate: ({ item, patch }) => {
      const prev = qc.getQueryData<LoadedItem>(itemKey(project.id, item.ref))
      if (prev)
        qc.setQueryData<LoadedItem>(itemKey(project.id, item.ref), {
          ...prev,
          item: { ...prev.item, ...patch } as Item,
        })
      return { prev }
    },
    onError: (error, { item }, ctx) => {
      if (ctx?.prev) qc.setQueryData(itemKey(project.id, item.ref), ctx.prev)
      onFail(error)
    },
    onSettled: () => refreshLists(qc),
  })
}

export function useDeleteItem(project: Project, kind: ItemKind) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (item: Item) =>
      api.delete(`/${KINDS[kind].endpoint}/${item.id}`),
    onSuccess: (_d, item) => {
      qc.removeQueries({ queryKey: itemKey(project.id, item.ref) })
      toast.success(`${KINDS[kind].label} #${item.ref} deleted`)
    },
    onError: onFail,
    onSettled: () => refreshLists(qc),
  })
}

/** Watch or unwatch; vote or unvote (issues and epics). */
export function useToggle(
  project: Project,
  kind: ItemKind,
  action: 'watch' | 'vote'
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (item: Item) => {
      const on = action === 'watch' ? item.is_watcher : item.is_voter
      const verb =
        action === 'watch'
          ? on
            ? 'unwatch'
            : 'watch'
          : on
            ? 'downvote'
            : 'upvote'
      await api.post(`/${KINDS[kind].endpoint}/${item.id}/${verb}`)
    },
    onError: onFail,
    onSettled: (_d, _e, item) =>
      qc.invalidateQueries({ queryKey: itemKey(project.id, item.ref) }),
  })
}

/* ---------- attachments ---------- */

/** Work items and wiki pages both take attachments. */
export type AttachableKind = ItemKind | 'wiki'
const attachmentBase = (kind: AttachableKind) =>
  kind === 'wiki' ? 'wiki' : KINDS[kind].endpoint

const attachmentsKey = (kind: AttachableKind, id: Id) =>
  ['attachments', kind, id] as const

export function useAttachments(project: Project, kind: AttachableKind, id: Id) {
  // Item ids are global per kind, so the project is implied.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  return useQuery({
    queryKey: attachmentsKey(kind, id),
    queryFn: async () =>
      (
        await api.get<Attachment[]>(`/${attachmentBase(kind)}/attachments`, {
          params: { project: project.id, object_id: id },
          ...ALL,
        })
      ).data,
  })
}

export function useUploadAttachment(
  project: Project,
  kind: AttachableKind,
  id: Id
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('project', String(project.id))
      form.append('object_id', String(id))
      form.append('attached_file', file)
      return (
        await api.post<Attachment>(
          `/${attachmentBase(kind)}/attachments`,
          form,
          { headers: { 'Content-Type': 'multipart/form-data' } }
        )
      ).data
    },
    onError: (error, file) =>
      toast.error(
        apiErrorMessage(error, `${file.name} could not be uploaded.`)
      ),
    onSettled: () =>
      qc.invalidateQueries({ queryKey: attachmentsKey(kind, id) }),
  })
}

export function useDeleteAttachment(kind: AttachableKind, id: Id) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (attachment: Attachment) =>
      api.delete(`/${attachmentBase(kind)}/attachments/${attachment.id}`),
    onError: onFail,
    onSettled: () =>
      qc.invalidateQueries({ queryKey: attachmentsKey(kind, id) }),
  })
}

/* ---------- custom attributes ---------- */

const customKindPath: Record<ItemKind, string> = {
  userstory: 'userstory',
  task: 'task',
  issue: 'issue',
  epic: 'epic',
}

export function useCustomAttributes(project: Project, kind: ItemKind) {
  return useQuery({
    queryKey: ['custom-attributes', kind, project.id],
    staleTime: 60_000,
    queryFn: async () =>
      (
        await api.get<CustomAttribute[]>(
          `/${customKindPath[kind]}-custom-attributes`,
          { params: { project: project.id } }
        )
      ).data.sort((a, b) => a.order - b.order),
  })
}

export function useCustomValues(kind: ItemKind, id: Id, enabled: boolean) {
  return useQuery({
    queryKey: ['custom-values', kind, id],
    enabled,
    queryFn: async () =>
      (
        await api.get<CustomAttributeValues>(
          `/${KINDS[kind].endpoint}/custom-attributes-values/${id}`
        )
      ).data,
  })
}

export function useUpdateCustomValues(kind: ItemKind, id: Id) {
  const qc = useQueryClient()
  const key = ['custom-values', kind, id]
  return useMutation({
    mutationFn: async (values: CustomAttributeValues['attributes_values']) => {
      const current = qc.getQueryData<CustomAttributeValues>(key)
      return (
        await api.patch<CustomAttributeValues>(
          `/${KINDS[kind].endpoint}/custom-attributes-values/${id}`,
          { attributes_values: values, version: current?.version ?? 1 }
        )
      ).data
    },
    onSuccess: (data) => qc.setQueryData(key, data),
    onError: onFail,
  })
}

/* ---------- comments and history ---------- */

const historyKey = (kind: ItemKind, id: Id) => ['history', kind, id] as const

export function useHistory(kind: ItemKind, id: Id) {
  return useQuery({
    queryKey: historyKey(kind, id),
    queryFn: async () =>
      (await api.get<HistoryChange[]>(`/history/${KINDS[kind].history}/${id}`))
        .data,
  })
}

export function useAddComment(project: Project, kind: ItemKind) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ item, comment }: { item: Item; comment: string }) =>
      patchItem(qc, project.id, kind, item, { comment }),
    onSuccess: (item) =>
      qc.invalidateQueries({ queryKey: historyKey(kind, item.id) }),
    onError: onFail,
  })
}

export function useEditComment(kind: ItemKind, id: Id) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ entry, comment }: { entry: string; comment: string }) =>
      api.post(
        `/history/${KINDS[kind].history}/${id}/edit_comment`,
        { comment },
        { params: { id: entry } }
      ),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: historyKey(kind, id) }),
  })
}

export function useDeleteComment(kind: ItemKind, id: Id) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (entry: string) =>
      api.post(`/history/${KINDS[kind].history}/${id}/delete_comment`, null, {
        params: { id: entry },
      }),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: historyKey(kind, id) }),
  })
}
