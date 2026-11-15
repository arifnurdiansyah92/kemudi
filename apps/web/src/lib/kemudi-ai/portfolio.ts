/**
 * The superadmin portfolio (apps/orchestrator `GET /portfolio`): Kemudi's
 * contract, scope-change, Awak and spend signals for every project, keyed by
 * slug, plus the projects this superadmin left out of the view.
 */
import { useMemo } from 'react'
import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Id, Milestone, ProjectSummary } from '@/lib/taiga/types'

const base = { baseURL: import.meta.env.VITE_KEMUDI_AI_URL ?? '/api/kemudi' }
const ALL = { headers: { 'x-disable-pagination': '1' } }

export type PortfolioSignals = {
  contract: {
    exists: boolean
    baseline_approved: number
    has_draft: boolean
    approved_at: string | null
    /** Sum of the approved baseline's item prices; null when unpriced. */
    value_idr: number | null
    show_prices: boolean
  }
  cr: {
    total: number
    in_baseline: number
    cr_candidate: number
    needs_clarification: number
    /** Checks with no PM verdict yet. */
    unreviewed: number
    /** AI-flagged change requests with no PM verdict yet. */
    unreviewed_cr: number
    agreed_cr: number
    agreed_cr_value_idr: number
    last_checked_at: string | null
  }
  backtest: {
    runs: number
    last_finished_at: string | null
    last_error: string | null
  }
  awak: {
    enabled: boolean
    queued: number
    running: number
    passed: number
    failed: number
    stopped: number
    failed_recent: number
    cost_idr: number
    last_error: string
    last_error_at: string | null
    last_activity_at: string | null
  }
  usage: {
    tokens: number
    cost_idr: number
    budget_tokens: number | null
    used_ratio: number | null
  }
}

type Portfolio = {
  generated_at: string
  month_start: string
  warn_at: number
  recent_days: number
  projects: Record<string, PortfolioSignals>
  excluded: string[]
}

const portfolioKey = ['kemudi-ai', 'portfolio'] as const

export function usePortfolio(enabled = true) {
  return useQuery({
    queryKey: portfolioKey,
    queryFn: async () => (await api.get<Portfolio>('/portfolio', base)).data,
    enabled,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  })
}

/** Remember which projects are left out (new projects stay in). */
export function useSetExcluded() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (excluded: string[]) =>
      (
        await api.put<{ excluded: string[] }>(
          '/portfolio/excluded',
          { excluded },
          base
        )
      ).data,
    onMutate: async (excluded) => {
      await qc.cancelQueries({ queryKey: portfolioKey })
      const prev = qc.getQueryData<Portfolio>(portfolioKey)
      if (prev) qc.setQueryData(portfolioKey, { ...prev, excluded })
      return { prev }
    },
    onError: (e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(portfolioKey, ctx.prev)
      onFail(e)
    },
  })
}

export type PortfolioProject = ProjectSummary & {
  total_activity_last_week?: number
  total_closed_milestones?: number | null
  is_featured?: boolean
}

/** Every project Taiga lets you see: all of them for a Taiga superuser. */
export function useAllProjects(enabled = true) {
  return useQuery({
    queryKey: ['projects', 'all'],
    queryFn: async () =>
      (
        await api.get<PortfolioProject[]>('/projects', {
          params: { order_by: 'name' },
          ...ALL,
        })
      ).data,
    enabled,
    staleTime: 5 * 60_000,
  })
}

export type OpenSprint = Pick<
  Milestone,
  | 'id'
  | 'name'
  | 'estimated_start'
  | 'estimated_finish'
  | 'total_points'
  | 'closed_points'
>

/** Each included project's open sprints (one request per project). */
export function useOpenSprints(projectIds: Id[]) {
  const { data, pending } = useQueries({
    queries: projectIds.map((id) => ({
      queryKey: ['portfolio', 'open-sprints', id] as const,
      queryFn: async () => {
        const rows = (
          await api.get<Milestone[]>('/milestones', {
            params: { project: id, closed: false },
            ...ALL,
          })
        ).data
        return rows.map(
          (m): OpenSprint => ({
            id: m.id,
            name: m.name,
            estimated_start: m.estimated_start,
            estimated_finish: m.estimated_finish,
            total_points: m.total_points,
            closed_points: m.closed_points,
          })
        )
      },
      staleTime: 5 * 60_000,
    })),
    combine: combineSprints,
  })
  // A stable map while the results are unchanged, so callers can memo on it.
  const key = projectIds.join(',')
  const byProject = useMemo(
    () => new Map(projectIds.map((id, i) => [id, data[i]] as const)),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by the ids' contents
    [data, key]
  )
  return { byProject, pending }
}

/** Module-level, so useQueries can keep its result between renders. */
function combineSprints(
  results: { data?: OpenSprint[]; isPending: boolean }[]
) {
  return {
    data: results.map((r) => r.data),
    pending: results.some((r) => r.isPending),
  }
}
