import { Link } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import { useTranslation } from 'react-i18next'
import type { Job } from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'

const STATE_DOT: Record<string, string> = {
  running: 'bg-primary',
  passed: 'bg-success',
  failed: 'bg-destructive',
}

const KNOWN_STATES = ['queued', 'running', 'passed', 'failed', 'stopped']
const KNOWN_MERGE = ['requested', 'merging', 'merged', 'failed']

export function Jobs({ slug, jobs }: { slug: string; jobs: Job[] }) {
  const { t } = useTranslation('agent')
  const f = useFormat()

  if (jobs.length === 0)
    return (
      <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
        {t('jobs.empty')}
      </p>
    )

  const head = 'px-3 py-2 text-start font-medium whitespace-nowrap'
  return (
    <div className='overflow-x-auto rounded-lg border'>
      <table className='w-full text-sm'>
        <thead className='bg-muted/50 text-xs text-muted-foreground'>
          <tr>
            <th className={head}>{t('jobs.story')}</th>
            <th className={head}>{t('jobs.state')}</th>
            <th className={head}>{t('jobs.phase')}</th>
            <th className={cn(head, 'text-end')}>{t('jobs.attempts')}</th>
            <th className={cn(head, 'text-end')}>{t('jobs.cost')}</th>
            <th className={head}>{t('jobs.branch')}</th>
            <th className={head}>{t('jobs.merge')}</th>
            <th className={head}>{t('jobs.updated')}</th>
          </tr>
        </thead>
        <tbody className='divide-y'>
          {jobs.map((j) => (
            <tr key={j.id} className='hover:bg-accent/40'>
              <td className='px-3 py-2'>
                <Link
                  to='/p/$slug/backlog'
                  params={{ slug }}
                  search={{ ref: j.story_ref }}
                  className='font-medium text-primary tabular-nums underline-offset-4 hover:underline'
                >
                  #{j.story_ref}
                </Link>
              </td>
              <td className='px-3 py-2 whitespace-nowrap'>
                <span className='flex items-center gap-1.5'>
                  <span
                    aria-hidden
                    className={cn(
                      'size-2 shrink-0 rounded-full',
                      STATE_DOT[j.state] ?? 'bg-muted-foreground/50'
                    )}
                  />
                  {KNOWN_STATES.includes(j.state)
                    ? t(`jobs.states.${j.state}` as 'jobs.states.queued')
                    : j.state}
                </span>
              </td>
              <td className='px-3 py-2 text-muted-foreground'>
                {j.phase || '—'}
              </td>
              <td className='px-3 py-2 text-end tabular-nums'>{j.attempts}</td>
              <td className='px-3 py-2 text-end whitespace-nowrap tabular-nums'>
                {f.rupiah(j.cost_idr)}
              </td>
              <td className='max-w-48 truncate px-3 py-2 font-mono text-xs text-muted-foreground'>
                {j.branch}
              </td>
              <td
                className={cn(
                  'px-3 py-2 whitespace-nowrap',
                  j.merge_state === 'failed' && 'text-destructive'
                )}
              >
                {KNOWN_MERGE.includes(j.merge_state)
                  ? t(
                      `jobs.mergeStates.${j.merge_state}` as 'jobs.mergeStates.merged'
                    )
                  : j.merge_state || t('jobs.mergeStates.none')}
                {j.merge_state === 'merged' && j.merged_sha && (
                  <span className='ms-1.5 font-mono text-xs text-muted-foreground'>
                    {j.merged_sha.slice(0, 7)}
                  </span>
                )}
              </td>
              <td className='px-3 py-2 text-xs whitespace-nowrap text-muted-foreground'>
                {j.updated_at ? f.timeAgo(j.updated_at) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
