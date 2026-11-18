import { useRef } from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import { AlertCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { agentError } from '@/lib/kemudi-ai/agent'
import {
  isProductRunActive,
  useProductAgents,
  useProductRuns,
  type ProductRunSummary,
} from '@/lib/kemudi-ai/product'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { useProject } from '@/features/project/use-project'
import { NewRun } from './new-run'
import { RunDetail } from './run-detail'
import { useStageText } from './run-meta'
import { StatusBadge } from './run-status'

/** Project → Product research: brief an agent, read its report later. */
export function Research() {
  const { t } = useTranslation('agent')
  const project = useProject()
  const slug = project.slug
  const { run: openId } = useSearch({
    from: '/_authenticated/p/$slug/research',
  })
  const navigate = useNavigate()
  const agents = useProductAgents(slug)
  const runs = useProductRuns(slug)
  const pane = useRef<HTMLDivElement>(null)

  /** On a phone the pane sits above the list: bring it back into view. */
  const showPane = () => {
    const el = pane.current
    if (el && el.getBoundingClientRect().top < 0)
      el.scrollIntoView({ block: 'start' })
  }
  const open = (run: number | undefined) => {
    void navigate({
      to: '/p/$slug/research',
      params: { slug },
      search: { run },
    })
    showPane()
  }

  return (
    <>
      <AppHeader
        crumbs={[
          { label: project.name, to: '/p/$slug', params: { slug } },
          { label: t('research.title') },
        ]}
      />
      <Main>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('research.title')}
        </h1>
        <p className='mt-1 max-w-2xl text-sm text-muted-foreground'>
          {t('research.intro')}
        </p>

        <div className='mt-8 grid gap-x-10 gap-y-10 lg:grid-cols-[20rem_minmax(0,1fr)]'>
          <div ref={pane} className='min-w-0 scroll-mt-20 lg:order-2'>
            {openId != null ? (
              <RunDetail
                key={openId}
                id={openId}
                agents={agents.data}
                onClose={() => open(undefined)}
              />
            ) : agents.data ? (
              <NewRun
                slug={slug}
                agents={agents.data}
                runs={runs.data ?? []}
                onStarted={(run) => open(run.id)}
              />
            ) : agents.isError ? (
              <Alert variant='destructive'>
                <AlertCircle />
                <AlertTitle>{t('research.unavailable')}</AlertTitle>
                <AlertDescription>{agentError(agents.error)}</AlertDescription>
              </Alert>
            ) : (
              <div className='grid gap-4' aria-busy='true'>
                <Skeleton className='h-5 w-32' />
                <div className='grid gap-2 sm:grid-cols-2'>
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className='h-20' />
                  ))}
                </div>
                <Skeleton className='h-28' />
              </div>
            )}
          </div>

          <RunList
            slug={slug}
            runs={runs.data}
            error={runs.error}
            openId={openId}
            onOpen={showPane}
          />
        </div>
      </Main>
    </>
  )
}

function RunList({
  slug,
  runs,
  error,
  openId,
  onOpen,
}: {
  slug: string
  runs: ProductRunSummary[] | undefined
  error: unknown
  openId: number | undefined
  onOpen: () => void
}) {
  const { t } = useTranslation('agent')
  return (
    <section
      className='grid min-w-0 content-start gap-3 lg:order-1'
      aria-labelledby='research-runs'
    >
      <h2 id='research-runs' className='text-base font-semibold'>
        {t('research.runs.title')}
        {runs && runs.length > 0 && (
          <span className='font-normal text-muted-foreground tabular-nums'>
            {' '}
            ({runs.length})
          </span>
        )}
      </h2>

      {runs ? (
        runs.length === 0 ? (
          <div className='rounded-lg border border-dashed px-4 py-6 text-sm'>
            <p className='font-medium'>{t('research.runs.emptyTitle')}</p>
            <p className='mt-1 text-muted-foreground'>
              {t('research.runs.emptyBody')}
            </p>
          </div>
        ) : (
          <ul className='divide-y overflow-hidden rounded-lg border bg-card'>
            {runs.map((run) => (
              <RunRow
                key={run.id}
                slug={slug}
                run={run}
                current={run.id === openId}
                onOpen={onOpen}
              />
            ))}
          </ul>
        )
      ) : error != null ? (
        <Alert variant='destructive'>
          <AlertCircle />
          <AlertTitle>{t('research.runs.loadFailed')}</AlertTitle>
          <AlertDescription>{agentError(error)}</AlertDescription>
        </Alert>
      ) : (
        <div className='grid gap-2' aria-busy='true'>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className='h-16' />
          ))}
        </div>
      )}
    </section>
  )
}

function RunRow({
  slug,
  run,
  current,
  onOpen,
}: {
  slug: string
  run: ProductRunSummary
  current: boolean
  onOpen: () => void
}) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const stage = useStageText()
  const kindLabel = t(`research.kinds.${run.kind}.label`)
  return (
    <li>
      <Link
        to='/p/$slug/research'
        params={{ slug }}
        search={{ run: run.id }}
        aria-current={current ? 'true' : undefined}
        onClick={onOpen}
        className={cn(
          'grid gap-1 px-4 py-3 text-sm transition-colors outline-none hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:ring-inset',
          current && 'bg-accent hover:bg-accent'
        )}
      >
        <span className='flex items-center justify-between gap-3'>
          <span className='min-w-0 truncate text-xs text-muted-foreground'>
            {kindLabel}
          </span>
          <StatusBadge status={run.status} />
        </span>
        <span className='line-clamp-2 font-medium break-words'>
          {run.title || kindLabel}
        </span>
        <span className='text-xs text-muted-foreground'>
          {run.created_by} <span aria-hidden>·</span>{' '}
          <time dateTime={run.created_at}>{f.timeAgo(run.created_at)}</time>
        </span>
        {isProductRunActive(run) && (
          <span className='text-xs text-muted-foreground'>{stage(run)}</span>
        )}
      </Link>
    </li>
  )
}
