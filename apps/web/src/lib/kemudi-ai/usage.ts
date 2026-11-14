/**
 * Awak usage and budget (apps/orchestrator, /projects/{slug}/agent/usage).
 * Members read; admins set the monthly token budget, the per-story cap and
 * the project's price override.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/taiga/client'
import { agentError } from './agent'

const base = { baseURL: import.meta.env.VITE_KEMUDI_AI_URL ?? '/api/kemudi' }

export type Currency = 'USD' | 'IDR'
export const currencies: Currency[] = ['USD', 'IDR']

/** Per 1M tokens. */
export type PriceIn = {
  input: number
  cached_input: number | null
  output: number
  currency: Currency
}

export type StoryUsage = {
  job_id: number
  story_ref: number
  state: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  tokens: number
  cost_idr: number
  cost_unknown: boolean
  updated_at: string | null
}

export type AgentUsage = {
  month_start: string
  calls: number
  prompt_tokens: number
  cached_tokens: number
  completion_tokens: number
  tokens: number
  /** The known part; see unknown_cost_calls. */
  cost_idr: number
  unknown_cost_calls: number
  unreported_calls: number
  setup_tokens: number
  setup_cost_idr: number
  budget: {
    monthly_tokens: number | null
    story_cap: number | null
    used_ratio: number | null
    warning: boolean
    exceeded: boolean
    recommended_monthly_tokens: number
  }
  price: {
    model: string
    source: 'project' | 'table' | 'flat' | null
    input: number | null
    cached_input: number | null
    output: number | null
    currency: Currency | null
  }
  price_override: PriceIn | null
  usd_idr_rate: number
  stories: StoryUsage[]
}

export type BudgetIn = {
  monthly_tokens: number | null
  story_cap: number | null
  price: PriceIn | null
}

const usageKey = (slug: string) => ['kemudi-ai', slug, 'agent', 'usage']

export function useAgentUsage(slug: string) {
  return useQuery({
    queryKey: usageKey(slug),
    queryFn: async () =>
      (await api.get<AgentUsage>(`/projects/${slug}/agent/usage`, base)).data,
    refetchInterval: 60_000,
  })
}

export function useSaveBudget(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: BudgetIn) =>
      (
        await api.put<AgentUsage>(
          `/projects/${slug}/agent/usage/budget`,
          body,
          base
        )
      ).data,
    onSuccess: (data) => qc.setQueryData(usageKey(slug), data),
    onError: (error) => toast.error(agentError(error)),
  })
}
