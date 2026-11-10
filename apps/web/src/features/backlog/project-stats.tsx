import { useFormat } from '@/i18n/format'
import { Trans, useTranslation } from 'react-i18next'
import { useProjectStats } from '@/lib/taiga/sprints'
import type { Project } from '@/lib/taiga/types'

/** Closed against total points, and the team's speed per sprint. */
export function ProjectStats({ project }: { project: Project }) {
  const { t } = useTranslation(['backlog', 'common'])
  const { number } = useFormat()
  const fmt = (n: number) => number(n, { maximumFractionDigits: 1 })
  const { data } = useProjectStats(project.id)
  if (!data) return null
  // Without a target set in admin, measure against estimated work.
  const total = data.total_points ?? data.defined_points
  const pct = total > 0 ? Math.min(100, (data.closed_points / total) * 100) : 0

  return (
    <div className='grid w-full max-w-md gap-1.5 text-sm'>
      <div className='flex items-baseline justify-between gap-4 tabular-nums'>
        <span>
          <Trans
            t={t}
            i18nKey='backlog.stats.closed'
            values={{ closed: fmt(data.closed_points), total: fmt(total) }}
            components={{
              strong: <span className='font-medium' />,
              muted: <span className='text-muted-foreground' />,
            }}
          />
        </span>
        <span className='text-xs text-muted-foreground'>
          {t('backlog.stats.speed', { speed: fmt(data.speed) })}
        </span>
      </div>
      <div
        className='h-1.5 overflow-hidden rounded-full bg-muted'
        role='progressbar'
        aria-label={t('backlog.stats.progress')}
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className='h-full bg-success' style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
