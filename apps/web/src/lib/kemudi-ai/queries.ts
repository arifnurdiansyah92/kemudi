/**
 * Kemudi AI (apps/orchestrator): contract, baseline and backtests. It sits
 * behind the gateway at /api/kemudi and takes the same token as kemudi-back,
 * so it reuses the `api` client (and its token refresh) with another base.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'

const base = { baseURL: import.meta.env.VITE_KEMUDI_AI_URL ?? '/api/kemudi' }

export type ScopeLabel = 'in_baseline' | 'cr_candidate' | 'needs_clarification'
export const scopeLabels: ScopeLabel[] = [
  'in_baseline',
  'cr_candidate',
  'needs_clarification',
]

export type RateCard = { currency: string; per_day: Record<string, number> }

export type Section = { ref: string; title: string; text: string }

export type BaselineItem = {
  ref: string
  kind: 'epic' | 'story' | 'obligation' | 'term'
  title: string
  description: string
  acceptance: string[]
  clauses: string[]
  price_idr: number | null
  parent: string | null
}

export type BaselineVersion = {
  id: number
  number: number
  status: 'draft' | 'approved'
  items: BaselineItem[]
  approved_by: string | null
  approved_at: string | null
}

export type BacktestRunInfo = {
  id: number
  dataset_name: string
  baseline_version_id: number
  started_at: string
  finished_at: string | null
  error: string | null
}

export type ContractState = {
  contract: {
    filename: string
    lang: 'id' | 'en'
    rate_card: RateCard
    sections: Section[]
    created_at: string
  } | null
  baseline: {
    draft: BaselineVersion | null
    approved: BaselineVersion | null
    history: BaselineVersion[]
  } | null
  runs: BacktestRunInfo[]
}

export type Prediction = {
  label: ScopeLabel
  reason: string
  clause: string
  effort_days: Record<string, number>
  price_idr: number
  question: string | null
}

export type Expected = {
  label: ScopeLabel
  reason?: string
  price_idr?: number
  waived?: boolean
}

export type BacktestResult = {
  id: number
  ticket_id: string
  source: string
  date: string
  text: string
  expected: Expected
  predicted: (Prediction & { error?: undefined }) | { error: string } | null
  status: 'ok' | 'error'
  verdict: 'right' | 'wrong' | null
}

export type Metrics = {
  total: number
  errors: number
  correct: number
  accuracy: number | null
  per_label: Record<
    ScopeLabel,
    { expected: number; predicted: number; correct: number }
  >
  confusion: Record<ScopeLabel, Record<ScopeLabel | 'error', number>>
  cr_recall: number | null
  false_cr_rate: number | null
  value_expected_idr: number
  value_predicted_idr: number
  value_caught_idr: number
  verdicts: { right: number; wrong: number; pending: number }
}

export type Backtest = {
  run: BacktestRunInfo
  results: BacktestResult[]
  metrics: Metrics
}

export function isPrediction(p: BacktestResult['predicted']): p is Prediction {
  return !!p && 'label' in p
}

const contractKey = (slug: string) => ['kemudi-ai', slug, 'contract']
const runKey = (slug: string, run: number) => ['kemudi-ai', slug, 'run', run]

function invalidate(qc: QueryClient, slug: string) {
  return qc.invalidateQueries({ queryKey: ['kemudi-ai', slug] })
}

export function useContract(slug: string) {
  return useQuery({
    queryKey: contractKey(slug),
    queryFn: async () =>
      (await api.get<ContractState>(`/projects/${slug}/contract`, base)).data,
  })
}

export function useUploadContract(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      file: File
      lang: 'id' | 'en'
      rateCard: RateCard
    }) => {
      const form = new FormData()
      form.append('file', input.file)
      form.append('lang', input.lang)
      form.append('rate_card', JSON.stringify(input.rateCard))
      return (
        await api.post(`/projects/${slug}/contract`, form, {
          ...base,
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      ).data
    },
    onError: onFail,
    onSettled: () => invalidate(qc, slug),
  })
}

export function useSaveRateCard(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (rateCard: RateCard) =>
      (
        await api.put(
          `/projects/${slug}/contract/rate-card`,
          { rate_card: rateCard },
          base
        )
      ).data,
    onError: onFail,
    onSettled: () => invalidate(qc, slug),
  })
}

export function useGenerateDraft(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<BaselineVersion>(
          `/projects/${slug}/baseline/draft`,
          null,
          { ...base, timeout: 300_000 }
        )
      ).data,
    onError: onFail,
    onSettled: () => invalidate(qc, slug),
  })
}

export function useSaveDraft(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (items: BaselineItem[]) =>
      (
        await api.put<BaselineVersion>(
          `/projects/${slug}/baseline/draft`,
          { items },
          base
        )
      ).data,
    onError: onFail,
    onSettled: () => invalidate(qc, slug),
  })
}

export function useApproveBaseline(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<BaselineVersion>(
          `/projects/${slug}/baseline/approve`,
          null,
          base
        )
      ).data,
    onError: onFail,
    onSettled: () => invalidate(qc, slug),
  })
}

export function useStartBacktest(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (dataset: File) => {
      const form = new FormData()
      form.append('dataset', dataset)
      return (
        await api.post<{ run_id: number }>(
          `/projects/${slug}/backtests`,
          form,
          { ...base, headers: { 'Content-Type': 'multipart/form-data' } }
        )
      ).data
    },
    onError: onFail,
    onSettled: () => invalidate(qc, slug),
  })
}

export function useBacktest(slug: string, runId: number | null) {
  return useQuery({
    queryKey: runKey(slug, runId ?? 0),
    enabled: runId !== null,
    queryFn: async () =>
      (await api.get<Backtest>(`/projects/${slug}/backtests/${runId}`, base))
        .data,
    // Poll while the run is still classifying.
    refetchInterval: (q) => (q.state.data?.run.finished_at ? false : 3000),
  })
}

export function useSetVerdict(slug: string, runId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: {
      resultId: number
      verdict: 'right' | 'wrong' | null
    }) =>
      (
        await api.put(
          `/projects/${slug}/backtests/${runId}/results/${input.resultId}/verdict`,
          { verdict: input.verdict },
          base
        )
      ).data,
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: runKey(slug, runId) }),
  })
}
