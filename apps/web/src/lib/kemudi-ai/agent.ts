/**
 * Awak project setup (apps/orchestrator, /projects/{slug}/agent/...).
 * Reads need project membership, writes need project admin. Responses carry
 * public keys and fingerprints only; private keys never leave the server.
 */
import { AxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import i18n from '@/i18n'
import { toast } from 'sonner'
import { api, apiErrorMessage } from '@/lib/taiga/client'

const base = { baseURL: import.meta.env.VITE_KEMUDI_AI_URL ?? '/api/kemudi' }

export type MergeMode = 'manual' | 'approve' | 'auto'
export const mergeModes: MergeMode[] = ['manual', 'approve', 'auto']
export type Executor = 'local' | 'ssh'
/** How much Awak checks before a story is Done: nothing, the repo's gates,
 * or gates plus browser QA. Auto merge needs `browser`. */
export type QaMode = 'off' | 'gates' | 'browser'
export const qaModes: QaMode[] = ['off', 'gates', 'browser']

export type Preflight = {
  ok: boolean
  cpu: number | null
  ram_gb: number | null
  disk_gb: number | null
  docker: string | null
  arch: string | null
  slots: number
  problems: string[]
  host_key: string | null
  checked_at: string
  error: string | null
  minimum: { cpu: number; ram_gb: number; disk_gb: number }
  executor: Executor
  remote_execution: boolean
}

export type AgentSettingsIn = {
  enabled: boolean
  merge_mode: MergeMode
  qa_mode: QaMode
  deploy_command: string
  executor: Executor
  ssh_host: string
  ssh_port: number
  ssh_user: string
}

export type AgentSettings = Omit<AgentSettingsIn, 'deploy_command'> & {
  /** Admins only (it may hold a token); `null` for other members. */
  deploy_command: string | null
  deploy_command_set: boolean
  ssh_public_key: string | null
  ssh_fingerprint: string | null
  /** `{}` until the first check. */
  preflight: Preflight | Record<string, never>
  remote_execution: boolean
  /** Whether the Awak bot user can open the project in Taiga. */
  bot_access: BotAccess
  /** The worker's last failure for this project; cleared on its next good pass. */
  last_error: string | null
  last_error_at: string | null
  updated_by: string | null
  updated_at: string | null
}

/** `member` is null when it could not be told (bot not configured, Taiga down). */
export type BotAccess = {
  ok: boolean
  member: boolean | null
  error: string | null
}

export type BotAccessGrant = {
  added: boolean
  role: string | null
  bot_access: BotAccess
}

export type KeyPair = { public_key: string; fingerprint: string }

export type RepoRole = 'web' | 'api' | 'mobile' | 'other'
export const repoRoles: RepoRole[] = ['web', 'api', 'mobile', 'other']
export const commandFields = [
  'install_cmd',
  'check_cmd',
  'build_cmd',
  'run_cmd',
] as const
export type CommandField = (typeof commandFields)[number]

export type RepoIn = {
  name: string
  role: RepoRole
  url: string
  default_branch: string
  subdir: string
} & Record<CommandField, string>

/** An app Check access found in the repo or one of its subfolders. */
export type DetectedApp = {
  /** Relative to the repo root; `''` is the root. */
  dir: string
  kind: string
  commands: Partial<Record<CommandField, string>>
}

export type RepoCheck = {
  ok: boolean
  clone: boolean
  push: boolean
  default_branch_found: boolean
  host_key: string | null
  detected: Partial<Record<CommandField, string>>
  /** Older checks have none. */
  apps?: DetectedApp[]
  error: string | null
  checked_at?: string
}

export const emptyRepo: RepoIn = {
  name: '',
  role: 'web',
  url: '',
  default_branch: 'main',
  subdir: '',
  install_cmd: '',
  check_cmd: '',
  build_cmd: '',
  run_cmd: '',
}

export type Repo = RepoIn & {
  id: number
  has_key: boolean
  public_key: string | null
  fingerprint: string | null
  /** Kemudi's own repo on the host: no deploy key needed. */
  local: boolean
  last_check: RepoCheck | Record<string, never>
}

export type RoleTemplate = 'frontend' | 'backend' | 'fullstack' | 'qa'
export const roleTemplates: RoleTemplate[] = [
  'frontend',
  'backend',
  'fullstack',
  'qa',
]
/** `both`: stories touching web and backend, and single-area stories no
 * other role covers. */
export type RoleArea = 'web' | 'backend' | 'both' | 'qa'
export const roleAreas: RoleArea[] = ['web', 'backend', 'both', 'qa']
export const OVERLAY_MAX = 8000

export type RoleIn = {
  name: string
  template: RoleTemplate
  area: RoleArea
  model: string
  repo_ids: number[]
  allowed_paths: string[]
  denied_paths: string[]
  prompt_overlay: string
  enabled: boolean
}

export type Role = RoleIn & {
  id: number
  version: number
  prompt_version: string
  updated_by: string | null
  updated_at: string | null
} & LlmEffective

/* ---------- model connection (BYOK) ---------- */

/** Where a model connection comes from: agent > project > server default. */
export type LlmSource = 'agent' | 'project' | 'server'

export type LlmEffective = {
  llm_source: LlmSource
  llm_model: string
  llm_host: string
}

/** One level (project or agent) as the API shows it. The key is write-only:
 * only whether one is stored and its last 4 characters come back. */
export type LlmLevel = {
  set: boolean
  base_url: string
  model: string
  key_set: boolean
  key_last4: string | null
  effective: LlmEffective
  server_default: { model: string; host: string }
  updated_by: string | null
  updated_at: string | null
}

/** An empty `api_key` keeps the stored key; `clear` removes the level. */
export type LlmIn = {
  base_url: string
  model: string
  api_key?: string
  clear?: boolean
}

export type LlmTest = {
  ok: boolean
  latency_ms: number
  status: number | null
  error: string | null
} & LlmEffective

/** What to list models for: unsaved values when `base_url` is set (a stored
 * key is reused only for the base URL it was saved with), else the saved
 * connection that applies to `role_id` (or the project). */
export type LlmModelsIn = {
  role_id?: number
  base_url?: string
  api_key?: string
}

export type LlmModels = {
  ok: boolean
  models: string[]
  source: LlmSource
  host: string
  error: string | null
}

export type RolePrompt = {
  fixed: string
  role: string
  scope: { repos: string[]; allowed_paths: string[]; denied_paths: string[] }
  overlay: string
  reminder: string
  rendered: string
  version: string
}

export type JobState =
  | 'queued'
  | 'running'
  | 'passed'
  | 'failed'
  | 'stopped'
  | (string & {})
export type MergeState =
  | ''
  | 'requested'
  | 'merging'
  | 'merged'
  | 'failed'
  | (string & {})

export type Job = {
  id: number
  story_id: number
  story_ref: number
  branch: string
  state: JobState
  phase: string
  attempts: number
  cost_idr: number
  repo_id: number | null
  role_id: number | null
  prompt_version: string
  merge_state: MergeState
  merged_sha: string
  started_at: string | null
  updated_at: string | null
}

export function hasPreflight(p: AgentSettings['preflight']): p is Preflight {
  return 'slots' in p
}

/** The PUT body from a repo as read. */
export function repoBody(r: Repo): RepoIn {
  return {
    name: r.name,
    role: r.role,
    url: r.url,
    default_branch: r.default_branch,
    subdir: r.subdir,
    install_cmd: r.install_cmd,
    check_cmd: r.check_cmd,
    build_cmd: r.build_cmd,
    run_cmd: r.run_cmd,
  }
}

export function hasCheck(c: Repo['last_check']): c is RepoCheck {
  return 'ok' in c
}

/**
 * FastAPI answers `{detail: "..."}` or, for validation, `{detail: [{msg}]}`;
 * show the server's words, they name the field and the fix.
 */
export function agentError(error: unknown) {
  if (error instanceof AxiosError) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)
      ?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string; loc?: unknown[] }
      const field = first.loc?.[first.loc.length - 1]
      if (first.msg)
        return typeof field === 'string' && field !== 'body'
          ? `${field}: ${first.msg}`
          : first.msg
    }
  }
  return apiErrorMessage(error, i18n.t('shell:toast.notSaved'))
}

function onFail(error: unknown) {
  toast.error(agentError(error))
}

const agentKey = (slug: string, ...rest: (string | number)[]) => [
  'kemudi-ai',
  slug,
  'agent',
  ...rest,
]

function useInvalidate(slug: string) {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: agentKey(slug) })
}

/* ---------- settings ---------- */

export function useAgentSettings(slug: string) {
  return useQuery({
    queryKey: agentKey(slug, 'settings'),
    queryFn: async () =>
      (await api.get<AgentSettings>(`/projects/${slug}/agent/settings`, base))
        .data,
  })
}

export function useSaveAgentSettings(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: AgentSettingsIn) =>
      (
        await api.put<AgentSettings>(
          `/projects/${slug}/agent/settings`,
          body,
          base
        )
      ).data,
    onSuccess: (data) => qc.setQueryData(agentKey(slug, 'settings'), data),
    onError: onFail,
  })
}

/** The PUT body from the settings as read: the API takes every field. Only
 * admins write, and admins always read the deploy command. */
export function settingsBody(s: AgentSettings): AgentSettingsIn {
  return {
    enabled: s.enabled,
    merge_mode: s.merge_mode,
    qa_mode: s.qa_mode,
    deploy_command: s.deploy_command ?? '',
    executor: s.executor,
    ssh_host: s.ssh_host,
    ssh_port: s.ssh_port,
    ssh_user: s.ssh_user,
  }
}

/** Make the Awak bot user a member of the Taiga project (admin's token). */
export function useGiveBotAccess(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<BotAccessGrant>(
          `/projects/${slug}/agent/bot-access`,
          null,
          base
        )
      ).data,
    onError: onFail,
    onSettled: () =>
      qc.invalidateQueries({ queryKey: agentKey(slug, 'settings') }),
  })
}

/* ---------- machine ---------- */

export function useMachineKey(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<KeyPair>(
          `/projects/${slug}/agent/machine/key`,
          null,
          base
        )
      ).data,
    onError: onFail,
    onSettled: invalidate,
  })
}

export function useMachineCheck(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<Preflight>(
          `/projects/${slug}/agent/machine/check`,
          null,
          {
            ...base,
            timeout: 120_000,
          }
        )
      ).data,
    onError: onFail,
    onSettled: invalidate,
  })
}

export function useForgetHostKey(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async () =>
      api.delete(`/projects/${slug}/agent/machine/host-key`, base),
    onError: onFail,
    onSettled: invalidate,
  })
}

/* ---------- repos ---------- */

export function useRepos(slug: string) {
  return useQuery({
    queryKey: agentKey(slug, 'repos'),
    queryFn: async () =>
      (await api.get<{ repos: Repo[] }>(`/projects/${slug}/agent/repos`, base))
        .data.repos,
  })
}

export function useSaveRepo(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async ({ id, ...body }: RepoIn & { id?: number }) =>
      (id
        ? await api.put<Repo>(`/projects/${slug}/agent/repos/${id}`, body, base)
        : await api.post<Repo>(`/projects/${slug}/agent/repos`, body, base)
      ).data,
    onError: onFail,
    onSettled: invalidate,
  })
}

export function useDeleteRepo(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async (id: number) =>
      api.delete(`/projects/${slug}/agent/repos/${id}`, base),
    onError: onFail,
    onSettled: invalidate,
  })
}

export function useGenerateRepoKey(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async (id: number) =>
      (
        await api.post<KeyPair>(
          `/projects/${slug}/agent/repos/${id}/key`,
          null,
          base
        )
      ).data,
    onError: onFail,
    onSettled: invalidate,
  })
}

export function useCheckRepo(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async (id: number) =>
      (
        await api.post<RepoCheck>(
          `/projects/${slug}/agent/repos/${id}/check`,
          null,
          { ...base, timeout: 600_000 }
        )
      ).data,
    onError: onFail,
    onSettled: invalidate,
  })
}

/* ---------- runbook ---------- */

/*
 * How to install, check, run and QA the project's apps. Typed loosely: the
 * server validates, and Edit JSON must round-trip fields this client does
 * not know yet.
 */
export type RunbookApp = {
  name: string
  repo: string
  dir: string
  install?: string[]
  checks?: string[]
  build?: string[]
  env?: Record<string, string>
  run_in?: string
  [key: string]: unknown
}

export type RunbookService = {
  name: string
  kind: 'process' | 'compose' | (string & {})
  app?: string
  command?: string
  repo?: string
  file?: string
  compose_services?: string[]
  expose?: string
  health: string
  ready_timeout?: number
  env?: string[] | Record<string, string>
  [key: string]: unknown
}

export type RunbookEnv = {
  name: string
  secret?: boolean
  required?: boolean
  description?: string
  [key: string]: unknown
}

export type Runbook = {
  apps?: RunbookApp[]
  services?: RunbookService[]
  env?: RunbookEnv[]
  seed?: { service: string; command: string } | null
  qa?: { service: string; env?: string[] } | null
  [key: string]: unknown
}

export type RunbookState = {
  runbook: Runbook | null
  version: number
  approved_by: string
  approved_at: string | null
}

/**
 * The runbook PUT answers 422 with `{detail: string | string[]}` (or
 * FastAPI's `[{loc, msg}]`); every problem is listed, not just the first.
 */
export function runbookErrors(error: unknown): string[] {
  if (error instanceof AxiosError && error.response?.status === 422) {
    const detail = (error.response.data as { detail?: unknown } | undefined)
      ?.detail
    if (typeof detail === 'string') return [detail]
    if (Array.isArray(detail)) {
      const lines = detail
        .map((d) => {
          if (typeof d === 'string') return d
          const { msg, loc } = (d ?? {}) as { msg?: string; loc?: unknown[] }
          if (!msg) return ''
          const path = (loc ?? []).filter((p) => p !== 'body').join('.')
          return path ? `${path}: ${msg}` : msg
        })
        .filter(Boolean)
      if (lines.length) return lines
    }
  }
  return [agentError(error)]
}

export function useRunbook(slug: string) {
  return useQuery({
    queryKey: agentKey(slug, 'runbook'),
    queryFn: async () =>
      (await api.get<RunbookState>(`/projects/${slug}/agent/runbook`, base))
        .data,
  })
}

/** Errors are listed by the editor, so no toast here. Settings are
 * refetched too: whether Browser QA is allowed depends on the runbook. */
export function useSaveRunbook(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (runbook: Runbook) =>
      (
        await api.put<RunbookState>(
          `/projects/${slug}/agent/runbook`,
          { runbook },
          base
        )
      ).data,
    onSuccess: (data) => {
      qc.setQueryData(agentKey(slug, 'runbook'), data)
      return qc.invalidateQueries({ queryKey: agentKey(slug, 'settings') })
    },
  })
}

/* ---------- roles ---------- */

export function useRoles(slug: string) {
  return useQuery({
    queryKey: agentKey(slug, 'roles'),
    queryFn: async () =>
      (
        await api.get<{ roles: Role[]; models: string[] }>(
          `/projects/${slug}/agent/roles`,
          base
        )
      ).data,
  })
}

export function useSaveRole(slug: string) {
  const invalidate = useInvalidate(slug)
  return useMutation({
    mutationFn: async ({ id, ...body }: RoleIn & { id?: number }) =>
      (id
        ? await api.put<Role>(`/projects/${slug}/agent/roles/${id}`, body, base)
        : await api.post<Role>(`/projects/${slug}/agent/roles`, body, base)
      ).data,
    onError: onFail,
    onSettled: invalidate,
  })
}

/** The PUT body from a role as read. */
export function roleBody(r: Role): RoleIn {
  return {
    name: r.name,
    template: r.template,
    area: r.area,
    model: r.model,
    repo_ids: r.repo_ids,
    allowed_paths: r.allowed_paths,
    denied_paths: r.denied_paths,
    prompt_overlay: r.prompt_overlay,
    enabled: r.enabled,
  }
}

export function useRolePrompt(slug: string, roleId: number | null) {
  return useQuery({
    queryKey: agentKey(slug, 'roles', roleId ?? 0, 'prompt'),
    enabled: roleId !== null,
    queryFn: async () =>
      (
        await api.get<RolePrompt>(
          `/projects/${slug}/agent/roles/${roleId}/prompt`,
          base
        )
      ).data,
  })
}

/* ---------- model connection (BYOK) ---------- */

/** `roleId` null is the project level ("all agents"). */
const llmPath = (slug: string, roleId: number | null) =>
  roleId === null
    ? `/projects/${slug}/agent/llm`
    : `/projects/${slug}/agent/roles/${roleId}/llm`

export function useLlmLevel(
  slug: string,
  roleId: number | null,
  enabled = true
) {
  return useQuery({
    queryKey: agentKey(slug, 'llm', roleId ?? 0),
    enabled,
    queryFn: async () =>
      (await api.get<LlmLevel>(llmPath(slug, roleId), base)).data,
  })
}

/** Errors are shown inline by the form, so no toast here. */
export function useSaveLlmLevel(slug: string, roleId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: LlmIn) =>
      (await api.put<LlmLevel>(llmPath(slug, roleId), body, base)).data,
    onSuccess: (data) => {
      qc.setQueryData(agentKey(slug, 'llm', roleId ?? 0), data)
      // Role rows show the resolved source; other levels' `effective` moves too.
      return qc.invalidateQueries({ queryKey: agentKey(slug) })
    },
  })
}

/** A role's own connection, for a role whose id is known only after it is
 * created. Errors are shown by the caller. */
export function useSaveRoleLlm(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ roleId, body }: { roleId: number; body: LlmIn }) =>
      (await api.put<LlmLevel>(llmPath(slug, roleId), body, base)).data,
    onSuccess: (data, { roleId }) => {
      qc.setQueryData(agentKey(slug, 'llm', roleId), data)
      return qc.invalidateQueries({ queryKey: agentKey(slug) })
    },
  })
}

/** Tests the unsaved values when a body is sent, else the saved connection. */
export function useTestLlmLevel(slug: string, roleId: number | null) {
  return useMutation({
    mutationFn: async (body: LlmIn | null) =>
      (
        await api.post<LlmTest>(`${llmPath(slug, roleId)}/test`, body, {
          ...base,
          timeout: 60_000,
        })
      ).data,
  })
}

/** A short, non-reversible tag so a typed key never sits in a query key. */
function keyTag(key: string) {
  let h = 0x811c9dc5
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(36)
}

/** The provider's model ids (admin only). Lists stay fresh for 5 minutes. */
export function useLlmModels(
  slug: string,
  body: LlmModelsIn,
  enabled: boolean
) {
  // The typed key is in the query key as a hash only; the rest of the body
  // is keyed as is.
  // eslint-disable-next-line @tanstack/query/exhaustive-deps
  return useQuery({
    queryKey: agentKey(
      slug,
      'llm-models',
      body.role_id ?? 0,
      body.base_url ?? '',
      body.api_key ? keyTag(body.api_key) : ''
    ),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async () =>
      (
        await api.post<LlmModels>(`/projects/${slug}/agent/llm/models`, body, {
          ...base,
          timeout: 20_000,
        })
      ).data,
  })
}

/* ---------- jobs ---------- */

export function isJobActive(j: Job) {
  return (
    j.state === 'running' ||
    j.merge_state === 'requested' ||
    j.merge_state === 'merging'
  )
}

export function useAgentJobs(slug: string) {
  return useQuery({
    queryKey: agentKey(slug, 'jobs'),
    queryFn: async () =>
      (await api.get<{ jobs: Job[] }>(`/projects/${slug}/agent/jobs`, base))
        .data.jobs,
    refetchInterval: (q) => (q.state.data?.some(isJobActive) ? 10_000 : false),
  })
}

/* ---------- story: merge on approve ---------- */

export const AWAITING_MERGE_TAG = 'awaiting-merge'

export type StoryAgent = {
  job: Job | null
  merge_mode: MergeMode
  can_merge: boolean
  merge_state: MergeState
  merge_error: string
}

export function isMergePending(state: MergeState) {
  return state === 'requested' || state === 'merging'
}

/** Awak's job for a story; polls every 5 s while a merge is pending. */
export function useStoryAgent(slug: string, storyId: number, enabled = true) {
  return useQuery({
    queryKey: agentKey(slug, 'stories', storyId),
    enabled,
    queryFn: async () =>
      (
        await api.get<StoryAgent>(
          `/projects/${slug}/agent/stories/${storyId}`,
          base
        )
      ).data,
    refetchInterval: (q) =>
      q.state.data && isMergePending(q.state.data.merge_state) ? 5_000 : false,
  })
}

export function useMergeStory(slug: string, storyId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<{ merge_state: MergeState }>(
          `/projects/${slug}/agent/stories/${storyId}/merge`,
          null,
          base
        )
      ).data,
    onSuccess: ({ merge_state }) =>
      qc.setQueryData<StoryAgent>(
        agentKey(slug, 'stories', storyId),
        (prev) => prev && { ...prev, merge_state, merge_error: '' }
      ),
    onError: onFail,
    onSettled: () =>
      qc.invalidateQueries({ queryKey: agentKey(slug, 'stories', storyId) }),
  })
}

/* ---------- intake ---------- */

export type IntakeArea = 'web' | 'backend' | 'both'
export const intakeAreas: IntakeArea[] = ['web', 'backend', 'both']
export const INTAKE_MAX_DRAFTS = 30
export const INTAKE_MAX_CRITERIA = 10

export type IntakeDraftOut = {
  subject: string
  description: string
  criteria: string[]
  area: IntakeArea
  ready: boolean
  reason: string
}

export type IntakeDraftIn = {
  subject: string
  description: string
  criteria: string[]
  area: IntakeArea
  hold: boolean
}

export type IntakeStory = {
  id: number
  ref: number
  subject: string
  ready: boolean
  reason: string
}

/** Drafts only, nothing reaches Taiga. The model can take half a minute. */
export function useIntakeDraft(slug: string) {
  return useMutation({
    mutationFn: async (input: {
      text: string
      lang: 'id' | 'en'
      file: File | null
    }) => {
      const form = new FormData()
      form.append('text', input.text)
      form.append('lang', input.lang)
      if (input.file) form.append('file', input.file)
      return (
        await api.post<{ drafts: IntakeDraftOut[] }>(
          `/projects/${slug}/intake/draft`,
          form,
          {
            ...base,
            timeout: 180_000,
            // The shared client defaults to JSON, which makes axios turn a
            // FormData body into JSON; the orchestrator expects multipart.
            headers: { 'Content-Type': 'multipart/form-data' },
          }
        )
      ).data.drafts
    },
  })
}

/** Creates the stories with the caller's own Taiga rights. */
export function useIntakeCreate(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (drafts: IntakeDraftIn[]) =>
      (
        await api.post<{ stories: IntakeStory[] }>(
          `/projects/${slug}/intake/create`,
          { drafts },
          { ...base, timeout: 120_000 }
        )
      ).data.stories,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['stories'] }),
  })
}
