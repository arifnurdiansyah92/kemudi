import { describe, expect, it } from 'vitest'
import type { OpenSprint, PortfolioSignals } from '@/lib/kemudi-ai/portfolio'
import { currentSprint, health } from './health'

const NOW = new Date('2026-11-15T12:00:00Z')

function sprint(over: Partial<OpenSprint> = {}): OpenSprint {
  return {
    id: 1,
    name: 'Sprint 3',
    estimated_start: '2026-11-06',
    estimated_finish: '2026-11-24',
    total_points: 20,
    closed_points: 10,
    ...over,
  }
}

function signals(
  over: {
    contract?: Partial<PortfolioSignals['contract']>
    cr?: Partial<PortfolioSignals['cr']>
    awak?: Partial<PortfolioSignals['awak']>
    usage?: Partial<PortfolioSignals['usage']>
  } = {}
): PortfolioSignals {
  return {
    contract: {
      exists: true,
      baseline_approved: 1,
      has_draft: false,
      approved_at: null,
      value_idr: 100,
      show_prices: false,
      ...over.contract,
    },
    cr: {
      total: 0,
      in_baseline: 0,
      cr_candidate: 0,
      needs_clarification: 0,
      unreviewed: 0,
      unreviewed_cr: 0,
      agreed_cr: 0,
      agreed_cr_value_idr: 0,
      last_checked_at: null,
      ...over.cr,
    },
    backtest: { runs: 0, last_finished_at: null, last_error: null },
    awak: {
      enabled: false,
      queued: 0,
      running: 0,
      passed: 0,
      failed: 0,
      stopped: 0,
      failed_recent: 0,
      cost_idr: 0,
      last_error: '',
      last_error_at: null,
      last_activity_at: null,
      ...over.awak,
    },
    usage: {
      tokens: 0,
      cost_idr: 0,
      budget_tokens: null,
      used_ratio: null,
      ...over.usage,
    },
  }
}

describe('currentSprint', () => {
  it('measures time gone and points done of the running sprint', () => {
    const s = currentSprint([sprint()], NOW)!
    expect(s.elapsed).toBeCloseTo(0.5, 1)
    expect(s.done).toBe(0.5)
    expect(s.overdueDays).toBe(0)
  })

  it('ignores sprints that have not started', () => {
    expect(
      currentSprint([sprint({ estimated_start: '2026-12-01' })], NOW)
    ).toBeNull()
  })

  it('counts days past the end', () => {
    const s = currentSprint([sprint({ estimated_finish: '2026-11-10' })], NOW)!
    expect(s.overdueDays).toBe(5)
    expect(s.elapsed).toBe(1)
  })

  it('has no done share without points', () => {
    expect(currentSprint([sprint({ total_points: 0 })], NOW)!.done).toBeNull()
  })
})

describe('health', () => {
  it('is green with nothing to report', () => {
    expect(health(signals(), currentSprint([sprint()], NOW))).toEqual({
      level: 'green',
      reasons: [],
    })
  })

  it('turns amber when the sprint slips and red when it is far behind', () => {
    const slipping = currentSprint([sprint({ closed_points: 6 })], NOW)
    expect(health(undefined, slipping).level).toBe('amber')
    const behind = currentSprint([sprint({ closed_points: 2 })], NOW)
    expect(health(undefined, behind).reasons[0].key).toBe('sprintBehind')
    expect(health(undefined, behind).level).toBe('red')
  })

  it('is red for an overdue sprint', () => {
    const late = currentSprint(
      [sprint({ estimated_finish: '2026-11-10' })],
      NOW
    )
    expect(health(undefined, late).reasons[0]).toMatchObject({
      key: 'sprintOverdue',
      values: { count: 5 },
    })
  })

  it('reads scope, Awak and budget signals, worst first', () => {
    const h = health(
      signals({
        contract: { baseline_approved: 0 },
        cr: { unreviewed: 4, unreviewed_cr: 3 },
        awak: { enabled: true, failed_recent: 1 },
        usage: { used_ratio: 0.85 },
      }),
      null
    )
    expect(h.level).toBe('red')
    expect(h.reasons.map((r) => r.key)).toEqual([
      'crBacklog',
      'awakFailed',
      'noBaseline',
      'budgetNear',
    ])
  })

  it('is amber for a pending check or an Awak error', () => {
    expect(health(signals({ cr: { unreviewed: 1 } }), null).level).toBe('amber')
    expect(
      health(signals({ awak: { enabled: true, last_error: 'x' } }), null).level
    ).toBe('amber')
    expect(health(signals({ usage: { used_ratio: 1.2 } }), null).level).toBe(
      'red'
    )
  })
})
