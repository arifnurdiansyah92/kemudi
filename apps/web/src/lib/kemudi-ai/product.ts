/**
 * Product research (apps/orchestrator, /projects/{slug}/product/...). A member
 * starts one of four agents with a brief; the run works in the background on
 * the server for a few minutes and ends in a Markdown report.
 */
import { AxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/taiga/client'
import { agentError } from './agent'

const base = { baseURL: import.meta.env.VITE_KEMUDI_AI_URL ?? '/api/kemudi' }

export type ProductKind = 'competitor' | 'features' | 'report' | 'custom'
export const productKinds: ProductKind[] = [
  'competitor',
  'features',
  'report',
  'custom',
]

export type ProductRunStatus = 'queued' | 'running' | 'done' | 'failed'

export const PRODUCT_BRIEF_MAX = 4000
/** `custom` has nothing else to go on, so its brief is required. */
export const PRODUCT_BRIEF_MIN = 10
export const productPeriods = [7, 14, 30, 90] as const
export type ProductPeriod = (typeof productPeriods)[number]
export const PRODUCT_DEFAULT_PERIOD: ProductPeriod = 30

export type ProductAgent = { kind: ProductKind; needs_web: boolean }

export type ProductAgents = {
  /** Whether the server has the web research service. */
  web: boolean
  agents: ProductAgent[]
}

export type ProductRunOptions = {
  /** `report` only. */
  days?: number
  /** `features` only: id of a finished competitor run to build on. */
  based_on?: number
}

export type ProductRunSummary = {
  id: number
  kind: ProductKind
  title: string
  brief: string
  lang: 'id' | 'en'
  status: ProductRunStatus
  /** Machine key of the current step while running, else `''`. */
  stage: string
  /** Human-readable, set when the run failed. */
  error: string
  /** Whether the web was actually used. */
  web: boolean
  /** Username. */
  created_by: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  options: ProductRunOptions
}

export type ProductSuggestion = {
  title: string
  problem: string
  proposal: string
  value: string
  effort: 'S' | 'M' | 'L'
  area: 'web' | 'backend' | 'both'
  evidence: string
}

export type ProductSource = { title: string; url: string }

export type ProductRun = ProductRunSummary & {
  /** Markdown; `''` until the run is done. */
  report: string
  /** `features` runs only, else `[]`. */
  suggestions: ProductSuggestion[]
  sources: ProductSource[]
}

export type ProductRunIn = {
  kind: ProductKind
  brief: string
  lang: 'id' | 'en'
  options: ProductRunOptions
}

/** Still working: the page keeps polling while any run is in this state. */
export const isProductRunActive = (run: { status: ProductRunStatus }) =>
  run.status === 'queued' || run.status === 'running'

const POLL_MS = 4_000

const productKey = (slug: string, ...rest: (string | number)[]) => [
  'kemudi-ai',
  slug,
  'product',
  ...rest,
]

function onFail(error: unknown) {
  toast.error(agentError(error))
}

/** A 404 on a run: deleted, or a link to another project's run. */
export const isProductRunMissing = (error: unknown) =>
  error instanceof AxiosError && error.response?.status === 404

/** The four agents, and whether this server can research the web. */
export function useProductAgents(slug: string) {
  return useQuery({
    queryKey: productKey(slug, 'agents'),
    queryFn: async () =>
      (await api.get<ProductAgents>(`/projects/${slug}/product/agents`, base))
        .data,
    staleTime: 5 * 60_000,
  })
}

/** Newest first; polls every 4 s while any run is queued or running. */
export function useProductRuns(slug: string) {
  return useQuery({
    queryKey: productKey(slug, 'runs'),
    queryFn: async () =>
      (
        await api.get<{ runs: ProductRunSummary[] }>(
          `/projects/${slug}/product/runs`,
          { ...base, params: { limit: 30 } }
        )
      ).data.runs,
    refetchInterval: (q) =>
      q.state.data?.some(isProductRunActive) ? POLL_MS : false,
  })
}

/** One run with its report; polls every 4 s until it is done or failed. */
export function useProductRun(slug: string, id: number | undefined) {
  return useQuery({
    queryKey: productKey(slug, 'runs', id ?? 0),
    enabled: id != null,
    queryFn: async () =>
      (await api.get<ProductRun>(`/projects/${slug}/product/runs/${id}`, base))
        .data,
    // A missing run stays missing; other failures get the default retries.
    retry: (count, error) => !isProductRunMissing(error) && count < 2,
    refetchInterval: (q) =>
      q.state.data && isProductRunActive(q.state.data) ? POLL_MS : false,
  })
}

export function useStartProductRun(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: ProductRunIn) =>
      (
        await api.post<ProductRun>(
          `/projects/${slug}/product/runs`,
          input,
          base
        )
      ).data,
    onSuccess: (run) => {
      qc.setQueryData(productKey(slug, 'runs', run.id), run)
      return qc.invalidateQueries({
        queryKey: productKey(slug, 'runs'),
        exact: true,
      })
    },
    onError: onFail,
  })
}

export function useDeleteProductRun(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/projects/${slug}/product/runs/${id}`, base)
      return id
    },
    onSuccess: (id) => {
      qc.setQueryData<ProductRunSummary[]>(productKey(slug, 'runs'), (prev) =>
        prev?.filter((r) => r.id !== id)
      )
      return qc.invalidateQueries({
        queryKey: productKey(slug, 'runs'),
        exact: true,
      })
    },
    onError: onFail,
  })
}
