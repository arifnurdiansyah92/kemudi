import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { Backtest } from '@/lib/kemudi-ai/queries'
import { BacktestReport } from './backtest-report'

const zero = {
  in_baseline: 0,
  cr_candidate: 0,
  needs_clarification: 0,
  error: 0,
}

function data(overrides: Partial<Backtest['metrics']> = {}): Backtest {
  return {
    run: {
      id: 1,
      dataset_name: 'd.json',
      baseline_version_id: 1,
      started_at: '2026-11-11T00:00:00Z',
      finished_at: '2026-11-11T00:01:00Z',
      error: null,
    },
    results: [
      {
        id: 11,
        ticket_id: 'R1',
        source: 'real',
        date: '2026-07-01',
        text: 'Tolong tambah toggle villa',
        expected: { label: 'cr_candidate', price_idr: 7_500_000 },
        predicted: {
          label: 'cr_candidate',
          reason: 'Fitur baru',
          clause: 'B3',
          effort_days: { backend: 3 },
          price_idr: 4_500_000,
          question: null,
        },
        status: 'ok',
        verdict: null,
      },
    ],
    metrics: {
      total: 1,
      errors: 0,
      correct: 1,
      accuracy: 1,
      per_label: {
        in_baseline: { expected: 0, predicted: 0, correct: 0 },
        cr_candidate: { expected: 1, predicted: 1, correct: 1 },
        needs_clarification: { expected: 0, predicted: 0, correct: 0 },
      },
      confusion: {
        in_baseline: zero,
        cr_candidate: { ...zero, cr_candidate: 1 },
        needs_clarification: zero,
      },
      cr_recall: 1,
      false_cr_rate: null,
      value_expected_idr: 7_500_000,
      value_predicted_idr: 4_500_000,
      value_caught_idr: 7_500_000,
      verdicts: { right: 0, wrong: 0, pending: 1 },
      ...overrides,
    },
  }
}

describe('BacktestReport', () => {
  it('shows agreement and a dash for a rate with no data', async () => {
    const screen = await render(
      <BacktestReport data={data()} canReview onVerdict={() => {}} />
    )
    await expect.element(screen.getByText('Agreement with PM')).toBeVisible()
    await expect.element(screen.getByText('1 of 1 requests')).toBeVisible()
    await expect.element(screen.getByText('—')).toBeVisible()
  })

  it('reports a verdict for the result', async () => {
    const onVerdict = vi.fn()
    const screen = await render(
      <BacktestReport data={data()} canReview onVerdict={onVerdict} />
    )
    await screen.getByRole('button', { name: 'Mark suggestion right' }).click()
    expect(onVerdict).toHaveBeenCalledWith(11, 'right')
  })
})
