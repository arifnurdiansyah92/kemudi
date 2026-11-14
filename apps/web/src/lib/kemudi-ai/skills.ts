/**
 * The skill library (apps/orchestrator, /skills/...): Kemudi admins only,
 * except `useKemudiMe`, which any signed-in user reads.
 */
import { AxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import i18n from '@/i18n'
import { api } from '@/lib/taiga/client'
import type { ScanLevel, SkillSource } from './agent'

const base = { baseURL: import.meta.env.VITE_KEMUDI_AI_URL ?? '/api/kemudi' }

type KemudiMe = { id: number; username: string; kemudi_admin: boolean }

const meKey = ['kemudi-ai', 'me'] as const

/** Who the orchestrator thinks you are; `kemudi_admin` gates the library. */
export function useKemudiMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: async () => (await api.get<KemudiMe>('/me', base)).data,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export type SkillUse = { project: string; role: string; role_id: number }

export type LibrarySkill = {
  slug: string
  title: string
  description: string
  source: SkillSource
  license: string
  enabled: boolean
  version: number | null
  scan_level: ScanLevel
  used_by: SkillUse[]
  pending_versions: number
  updated_at: string
}

export type SkillLimits = {
  max_bytes: number
  max_files: number
  max_upload_bytes: number
  description_max: number
  description_agent_max: number
}

export type Library = { skills: LibrarySkill[]; limits: SkillLimits }

export type Severity = 'high' | 'medium' | 'low'

export type Finding = {
  rule: string
  severity: Severity
  path: string
  line: number
  excerpt: string
}

export type SkillVersion = {
  version: number
  sha256: string
  size: number
  files: number
  status: 'active' | 'pending'
  scan_level: ScanLevel
  created_by: string
  created_at: string
}

export type SkillFileEntry = { path: string; size: number; binary: boolean }

/** Where a marketplace skill came from, and its last update check. */
export type SkillOrigin = {
  marketplace_id?: number
  marketplace?: string
  repo?: string
  ref?: string
  sha?: string
  plugin?: string
  path?: string
  checked_at?: string
  checked_sha?: string
  check_status?: UpdateStatus
  [key: string]: unknown
}

export type FileDiff = { added: string[]; removed: string[]; changed: string[] }

/** A marketplace update awaiting approval (never used by runs). */
export type PendingVersion = {
  version: number
  sha256: string
  origin: { repo?: string; sha?: string; path?: string; license?: string }
  diff: FileDiff
  findings: Finding[]
  warnings: string[]
  scan_level: ScanLevel
  previous_scan_level: ScanLevel
  created_by: string
  created_at: string
}

export type SkillDetail = LibrarySkill & {
  origin: SkillOrigin
  /** Marketplace skills: the folder at the pinned commit on GitHub. */
  origin_url?: string
  pending?: PendingVersion[]
  created_by: string
  created_at: string
  versions: SkillVersion[]
  current: {
    version: number
    sha256: string
    files: SkillFileEntry[]
    findings: Finding[]
    warnings: string[]
    skill_md: string
    license_files: { path: string; text: string }[]
  } | null
}

export type SkillFile =
  | { path: string; size: number; text: string; binary?: undefined }
  | { path: string; size: number; binary: true; text?: undefined }

/** The editor's fields. `files`: extra text files, path → text. */
export type SkillDraft = {
  slug: string
  description: string
  body: string
  license: string
  files: Record<string, string>
}

export type DraftCheck = {
  ok: boolean
  problems: string[]
  warnings: string[]
  findings: Finding[]
  worst: ScanLevel
  skill_md: string
  agent_skill_md: string
  size: number
}

export type UploadResult = {
  skill: SkillDetail
  created: boolean
  unchanged: boolean
  disabled: boolean
  warnings: string[]
}

/** The server's refusal: `{detail: {message, problems, code?, ...}}`. */
export type SkillProblem = {
  status: number
  message: string
  problems: string[]
  code?:
    | 'exists'
    | 'not_local'
    | 'high_finding'
    | 'in_use'
    | 'builtin'
    | 'findings_rise'
    | 'conflict'
    | 'too_large'
    | string
  slug?: string
  version?: number
  /** `exists`: whether the skill is enabled (its roles get a new version). */
  enabled?: boolean
  used_by?: SkillUse[]
  findings?: Finding[]
  /** `findings_rise`: the new version's worst scan level and the current one's. */
  worst?: ScanLevel
  previous?: ScanLevel
}

export function skillProblem(error: unknown): SkillProblem {
  const fallback = i18n.t('common:errors.generic')
  if (!(error instanceof AxiosError) || !error.response)
    return { status: 0, message: fallback, problems: [] }
  const status = error.response.status
  const detail = (error.response.data as { detail?: unknown } | undefined)
    ?.detail
  if (typeof detail === 'string')
    return { status, message: detail, problems: [] }
  if (Array.isArray(detail))
    // FastAPI's own validation errors (field too long, …).
    return {
      status,
      message: fallback,
      problems: detail.map((d: { msg?: string }) => d.msg ?? String(d)),
    }
  if (detail && typeof detail === 'object') {
    const d = detail as Partial<SkillProblem>
    return {
      ...d,
      status,
      message: d.message ?? fallback,
      problems: d.problems ?? [],
    }
  }
  return { status, message: fallback, problems: [] }
}

const libraryKey = ['kemudi-ai', 'skill-library'] as const
const detailKey = (slug: string) => [...libraryKey, slug] as const

export function useSkillLibrary() {
  return useQuery({
    queryKey: libraryKey,
    queryFn: async () => (await api.get<Library>('/skills/library', base)).data,
  })
}

export function useSkillDetail(slug: string | null) {
  return useQuery({
    queryKey: detailKey(slug ?? ''),
    enabled: !!slug,
    queryFn: async () =>
      (await api.get<SkillDetail>(`/skills/${slug}`, base)).data,
  })
}

/** Each segment encoded: the server matches the stored key exactly. */
export function filePath(path: string) {
  return path.split('/').map(encodeURIComponent).join('/')
}

/**
 * A stored file's query key. Keyed by the version's sha too: a deleted and
 * recreated slug starts again at version 1, with other files.
 */
export function skillFileKey(
  slug: string,
  sha: string,
  version: number,
  path: string
) {
  return [...detailKey(slug), 'file', sha, version, path] as const
}

export function useSkillFile(
  slug: string,
  sha: string,
  version: number | null,
  path: string | null
) {
  return useQuery({
    queryKey: skillFileKey(slug, sha, version ?? 0, path ?? ''),
    enabled: version !== null && !!path,
    queryFn: async () =>
      (
        await api.get<SkillFile>(
          `/skills/${slug}/versions/${version}/files/${filePath(path!)}`,
          base
        )
      ).data,
    staleTime: Infinity, // versions are immutable
  })
}

/** After a write: the library, the detail, and the role editor's picker. */
function useRefresh() {
  const qc = useQueryClient()
  return (detail?: SkillDetail) => {
    if (detail) qc.setQueryData(detailKey(detail.slug), detail)
    void qc.invalidateQueries({ queryKey: libraryKey })
    void qc.invalidateQueries({ queryKey: ['kemudi-ai', 'skills'] })
  }
}

export function useSetSkillEnabled() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: async ({ slug, enabled }: { slug: string; enabled: boolean }) =>
      (
        await api.post<SkillDetail>(
          `/skills/${slug}/${enabled ? 'enable' : 'disable'}`,
          null,
          base
        )
      ).data,
    onSuccess: (d) => refresh(d),
  })
}

export function useDeleteSkill() {
  const qc = useQueryClient()
  const refresh = useRefresh()
  return useMutation({
    mutationFn: async (slug: string) =>
      (await api.delete<{ deleted: string }>(`/skills/${slug}`, base)).data,
    onSuccess: ({ deleted }) => {
      qc.removeQueries({ queryKey: detailKey(deleted) })
      refresh()
    },
  })
}

export function useUploadSkill() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: async ({
      file,
      replace,
      acceptFindings = false,
    }: {
      file: File
      replace: boolean
      /** Store a version whose scan is worse than the current one's, for roles that run it. */
      acceptFindings?: boolean
    }) => {
      const form = new FormData()
      form.append('file', file)
      const params = {
        ...(replace ? { replace: true } : {}),
        ...(acceptFindings ? { accept_findings: true } : {}),
      }
      return (
        await api.post<UploadResult>('/skills/upload', form, {
          ...base,
          params: Object.keys(params).length ? params : undefined,
        })
      ).data
    },
    onSuccess: (r) => refresh(r.skill),
  })
}

/** Create (no `existing`) or the next version of a local skill. */
export function useSaveSkill() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: async ({
      draft,
      existing,
      acceptFindings = false,
    }: {
      draft: SkillDraft
      existing: boolean
      /** See useUploadSkill. */
      acceptFindings?: boolean
    }) =>
      (existing
        ? await api.put<SkillDetail & { unchanged: boolean }>(
            `/skills/${draft.slug}`,
            draft,
            {
              ...base,
              params: acceptFindings ? { accept_findings: true } : undefined,
            }
          )
        : await api.post<SkillDetail>('/skills', draft, base)
      ).data,
    onSuccess: (d) => refresh(d),
  })
}

/** Dry-run validate + scan of the editor's draft (stores nothing). */
export function useCheckDraft(draft: SkillDraft | null) {
  return useQuery({
    queryKey: ['kemudi-ai', 'skill-draft', draft],
    enabled: draft !== null,
    queryFn: async () =>
      (await api.post<DraftCheck>('/skills/validate', draft, base)).data,
    placeholderData: (prev) => prev,
    staleTime: Infinity,
    retry: false,
  })
}

// --- marketplaces (/skill-marketplaces) ----------------------------------------

export type UpdateStatus =
  | 'up_to_date'
  | 'pending'
  | 'rejected'
  | 'invalid'
  | 'missing'

export type UpdateResult = {
  status: UpdateStatus
  sha: string
  version?: number
  new?: boolean
  problems?: string[]
  message?: string
}

export type Marketplace = {
  id: number
  name: string
  repo: string
  ref: string
  builtin: boolean
  url: string
  last_sha: string
  last_fetched_at: string | null
  error: string
  description: string
  plugin_count: number
  skill_count: number
  created_by: string
  created_at: string
}

export type MarketplaceSkill = {
  name: string
  path: string
  description: string
  license: string
  version: string
  valid: boolean
  problems: string[]
  scan_level: ScanLevel
  files: number
  size: number
  installed: {
    slug: string
    source: SkillSource
    version: number
    enabled: boolean
    same_origin: boolean
    sha: string
  } | null
}

export type PluginSource =
  | { type: 'relative'; path: string }
  | {
      type: 'github'
      repo: string
      ref: string
      sha: string
      resolved_sha?: string
    }
  | { type: string; [key: string]: unknown }

export type MarketplacePlugin = {
  name: string
  description: string
  version: string
  category: string
  source: PluginSource
  supported: boolean
  reason: string
  skills: MarketplaceSkill[]
}

export type MarketplaceListing = {
  marketplace: Marketplace
  refreshed: boolean
  owner: string
  kind: 'marketplace' | 'skills' | ''
  plugins: MarketplacePlugin[]
}

const marketsKey = ['kemudi-ai', 'skill-marketplaces'] as const
const pluginsKey = (id: number) => [...marketsKey, id, 'plugins'] as const

export function useMarketplaces() {
  return useQuery({
    queryKey: marketsKey,
    queryFn: async () =>
      (
        await api.get<{ marketplaces: Marketplace[] }>(
          '/skill-marketplaces',
          base
        )
      ).data.marketplaces,
  })
}

export function useMarketplacePlugins(id: number | null) {
  return useQuery({
    queryKey: pluginsKey(id ?? 0),
    enabled: id !== null,
    queryFn: async () =>
      (
        await api.get<MarketplaceListing>(
          `/skill-marketplaces/${id}/plugins`,
          base
        )
      ).data,
  })
}

function useMarketsRefresh() {
  const qc = useQueryClient()
  return (id?: number) => {
    void qc.invalidateQueries({ queryKey: marketsKey, exact: true })
    if (id !== undefined)
      void qc.invalidateQueries({ queryKey: pluginsKey(id) })
  }
}

/** `repo`: owner/repo, owner/repo@ref or a github.com URL. */
export function useAddMarketplace() {
  const refresh = useMarketsRefresh()
  return useMutation({
    mutationFn: async (repo: string) =>
      (await api.post<Marketplace>('/skill-marketplaces', { repo }, base)).data,
    onSuccess: () => refresh(),
  })
}

export function useDeleteMarketplace() {
  const qc = useQueryClient()
  const refresh = useMarketsRefresh()
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.delete<{ deleted: number }>(`/skill-marketplaces/${id}`, base))
        .data,
    onSuccess: ({ deleted }) => {
      qc.removeQueries({ queryKey: pluginsKey(deleted) })
      refresh()
    },
  })
}

/** Fetch the repo again (through kemudi-runner) and cache its listing. A
 * failure is kept on the marketplace, so the list is refreshed either way. */
export function useRefreshMarketplace() {
  const refresh = useMarketsRefresh()
  return useMutation({
    mutationFn: async (id: number) =>
      (
        await api.post<Marketplace>(
          `/skill-marketplaces/${id}/refresh`,
          null,
          base
        )
      ).data,
    onSettled: (_d, _e, id) => refresh(id),
  })
}

export function useInstallSkill() {
  const refresh = useRefresh()
  const refreshMarkets = useMarketsRefresh()
  return useMutation({
    mutationFn: async ({
      id,
      plugin,
      skill,
    }: {
      id: number
      plugin: string
      skill: string
    }) =>
      (
        await api.post<SkillDetail>(
          `/skill-marketplaces/${id}/install`,
          { plugin, skill },
          base
        )
      ).data,
    onSuccess: (d, { id }) => {
      refresh(d)
      refreshMarkets(id)
    },
  })
}

export function useCheckUpdate() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: async (slug: string) =>
      (
        await api.post<{ result: UpdateResult; skill: SkillDetail }>(
          `/skills/${slug}/check-update`,
          null,
          base
        )
      ).data,
    onSuccess: (r) => refresh(r.skill),
  })
}

export function useDecideVersion() {
  const refresh = useRefresh()
  return useMutation({
    mutationFn: async ({
      slug,
      version,
      decision,
      acceptFindings = false,
    }: {
      slug: string
      version: number
      decision: 'approve' | 'reject'
      /** Approve a version whose scan is worse than the current one's. */
      acceptFindings?: boolean
    }) =>
      (
        await api.post<SkillDetail & { disabled_now?: boolean }>(
          `/skills/${slug}/versions/${version}/${decision}`,
          null,
          {
            ...base,
            params: acceptFindings ? { accept_findings: true } : undefined,
          }
        )
      ).data,
    onSuccess: (d) => refresh(d),
  })
}
