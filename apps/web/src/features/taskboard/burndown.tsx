import { format } from 'date-fns'
import { useFormat } from '@/i18n/format'
import { useTranslation } from 'react-i18next'
import type { SprintStats } from '@/lib/taiga/sprints'

const W = 360
const H = 120
const PAD = { top: 8, right: 8, bottom: 18, left: 28 }

/**
 * Remaining points per day against the ideal line. Days after today have no
 * actual value yet, so the actual line stops at today.
 */
export function Burndown({ stats }: { stats: SprintStats }) {
  const { t } = useTranslation(['backlog', 'common'])
  const { date, number } = useFormat()
  const days = stats.days
  if (days.length < 2) return null
  const max = Math.max(
    1,
    ...days.map((d) => Math.max(d.open_points, d.optimal_points))
  )
  const today = format(new Date(), 'yyyy-MM-dd')
  const x = (i: number) =>
    PAD.left + (i / (days.length - 1)) * (W - PAD.left - PAD.right)
  const y = (v: number) => PAD.top + (1 - v / max) * (H - PAD.top - PAD.bottom)
  const line = (pts: [number, number][]) =>
    pts
      .map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`)
      .join('')

  const ideal = line(days.map((d, i) => [x(i), y(d.optimal_points)]))
  const actualDays = days.filter((d) => d.day <= today)
  const actual = line(actualDays.map((d, i) => [x(i), y(d.open_points)]))
  const last = actualDays[actualDays.length - 1]
  const dayLabel = (i: number) => date(days[i].day, 'dayMonth')

  return (
    <figure className='min-w-0'>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className='h-auto w-full max-w-[360px]'
        role='img'
        aria-label={
          last
            ? t('burndown.ariaProgress', {
                points: number(last.open_points),
                date: date(last.day),
                max: number(max),
              })
            : t('burndown.ariaNotStarted', { max: number(max) })
        }
      >
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(max * t)}
              y2={y(max * t)}
              className='stroke-border'
              strokeWidth={1}
            />
            <text
              x={PAD.left - 6}
              y={y(max * t) + 3}
              textAnchor='end'
              className='fill-muted-foreground text-[9px] tabular-nums'
            >
              {Math.round(max * t)}
            </text>
          </g>
        ))}
        <path
          d={ideal}
          fill='none'
          className='stroke-muted-foreground'
          strokeWidth={1.25}
          strokeDasharray='4 3'
        />
        {actualDays.length > 0 && (
          <path
            d={actual}
            fill='none'
            className='stroke-brass'
            strokeWidth={2}
          />
        )}
        {last && (
          <circle
            cx={x(actualDays.length - 1)}
            cy={y(last.open_points)}
            r={3}
            className='fill-brass'
          />
        )}
        {[0, days.length - 1].map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - 4}
            textAnchor={i ? 'end' : 'start'}
            className='fill-muted-foreground text-[9px]'
          >
            {dayLabel(i)}
          </text>
        ))}
      </svg>
      <figcaption className='mt-1 flex gap-4 text-xs text-muted-foreground'>
        <span className='inline-flex items-center gap-1.5'>
          <span className='h-0.5 w-4 bg-brass' aria-hidden='true' />
          {t('burndown.openPoints')}
        </span>
        <span className='inline-flex items-center gap-1.5'>
          <span
            className='h-0 w-4 border-t border-dashed border-muted-foreground'
            aria-hidden='true'
          />
          {t('burndown.ideal')}
        </span>
      </figcaption>
    </figure>
  )
}
