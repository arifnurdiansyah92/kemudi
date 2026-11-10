import { useProjectStats } from '@/lib/taiga/sprints'
import type { Project } from '@/lib/taiga/types'

const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1))

/** Closed against total points, and the team's speed per sprint. */
export function ProjectStats({ project }: { project: Project }) {
  const { data } = useProjectStats(project.id)
  if (!data) return null
  // Without a target set in admin, measure against estimated work.
  const total = data.total_points ?? data.defined_points
  const pct = total > 0 ? Math.min(100, (data.closed_points / total) * 100) : 0

  return (
    <div className='grid w-full max-w-md gap-1.5 text-sm'>
      <div className='flex items-baseline justify-between gap-4 tabular-nums'>
        <span>
          <span className='font-medium'>{fmt(data.closed_points)}</span>
          <span className='text-muted-foreground'>
            {' '}
            of {fmt(total)} points closed
          </span>
        </span>
        <span className='text-xs text-muted-foreground'>
          Speed {fmt(data.speed)} pts per sprint
        </span>
      </div>
      <div
        className='h-1.5 overflow-hidden rounded-full bg-muted'
        role='progressbar'
        aria-label='Project progress'
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className='h-full bg-success' style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
