/**
 * Red/amber/green health for one project on the portfolio. Every colour has a
 * reason a person can read and check; the worst reason sets the colour.
 */
import type { OpenSprint, PortfolioSignals } from '@/lib/kemudi-ai/portfolio'

export type Level = 'red' | 'amber' | 'green'

export type ReasonKey =
  | 'sprintOverdue'
  | 'sprintBehind'
  | 'sprintSlipping'
  | 'crBacklog'
  | 'crPending'
  | 'noBaseline'
  | 'awakFailed'
  | 'awakError'
  | 'budgetOver'
  | 'budgetNear'

export type Reason = {
  key: ReasonKey
  level: Exclude<Level, 'green'>
  values?: Record<string, string | number>
}

export type Health = { level: Level; reasons: Reason[] }

/** Points done trailing time elapsed by this much is amber; double is red. */
export const SLIP = 0.15
export const BEHIND = 0.3
/** This many change requests waiting for the PM's verdict is red. */
export const CR_BACKLOG = 3

const DAY = 86_400_000

export type SprintProgress = {
  sprint: OpenSprint
  /** Share of the sprint's time gone, 0..1. */
  elapsed: number
  /** Share of its points closed, 0..1; null when it has no points. */
  done: number | null
  overdueDays: number
}

/** The open sprint that matters now: the running one that ends soonest. */
export function currentSprint(
  sprints: OpenSprint[] | undefined,
  now: Date
): SprintProgress | null {
  if (!sprints?.length) return null
  const t = now.getTime()
  const started = sprints
    .filter((s) => new Date(s.estimated_start).getTime() <= t)
    .sort(
      (a, b) =>
        new Date(a.estimated_finish).getTime() -
        new Date(b.estimated_finish).getTime()
    )
  const s = started[0]
  if (!s) return null
  const start = new Date(s.estimated_start).getTime()
  // A sprint's finish date is a whole day: it ends at the end of that day.
  const finish = new Date(s.estimated_finish).getTime() + DAY
  const span = Math.max(finish - start, DAY)
  const elapsed = Math.min(Math.max((t - start) / span, 0), 1)
  const total = s.total_points ?? 0
  const done = total > 0 ? Math.min((s.closed_points ?? 0) / total, 1) : null
  const overdueDays = t > finish ? Math.ceil((t - finish) / DAY) : 0
  return { sprint: s, elapsed, done, overdueDays }
}

export function health(
  signals: PortfolioSignals | undefined,
  sprint: SprintProgress | null,
  warnAt = 0.8
): Health {
  const reasons: Reason[] = []

  if (sprint) {
    if (sprint.overdueDays > 0) {
      reasons.push({
        key: 'sprintOverdue',
        level: 'red',
        values: { name: sprint.sprint.name, count: sprint.overdueDays },
      })
    } else if (sprint.done !== null) {
      const gap = sprint.elapsed - sprint.done
      const values = {
        done: Math.round(sprint.done * 100),
        elapsed: Math.round(sprint.elapsed * 100),
      }
      if (gap > BEHIND)
        reasons.push({ key: 'sprintBehind', level: 'red', values })
      else if (gap > SLIP)
        reasons.push({ key: 'sprintSlipping', level: 'amber', values })
    }
  }

  if (signals) {
    const { contract, cr, awak, usage } = signals
    if (cr.unreviewed_cr >= CR_BACKLOG)
      reasons.push({
        key: 'crBacklog',
        level: 'red',
        values: { count: cr.unreviewed_cr },
      })
    else if (cr.unreviewed > 0)
      reasons.push({
        key: 'crPending',
        level: 'amber',
        values: { count: cr.unreviewed },
      })
    if (contract.exists && contract.baseline_approved === 0)
      reasons.push({ key: 'noBaseline', level: 'amber' })
    if (awak.failed_recent > 0)
      reasons.push({
        key: 'awakFailed',
        level: 'red',
        values: { count: awak.failed_recent },
      })
    else if (awak.enabled && awak.last_error)
      reasons.push({ key: 'awakError', level: 'amber' })
    if (usage.used_ratio !== null) {
      const pct = Math.round(usage.used_ratio * 100)
      if (usage.used_ratio >= 1)
        reasons.push({ key: 'budgetOver', level: 'red', values: { pct } })
      else if (usage.used_ratio >= warnAt)
        reasons.push({ key: 'budgetNear', level: 'amber', values: { pct } })
    }
  }

  reasons.sort((a, b) => (a.level === b.level ? 0 : a.level === 'red' ? -1 : 1))
  const level: Level = reasons.some((r) => r.level === 'red')
    ? 'red'
    : reasons.length
      ? 'amber'
      : 'green'
  return { level, reasons }
}

export const LEVELS: readonly Level[] = ['red', 'amber', 'green']
export const LEVEL_ORDER: Record<Level, number> = { red: 0, amber: 1, green: 2 }
