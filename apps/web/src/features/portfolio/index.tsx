import { useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import { RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  type PortfolioProject,
  type PortfolioSignals,
  useAllProjects,
  useOpenSprints,
  usePortfolio,
  useSetExcluded,
} from '@/lib/kemudi-ai/portfolio'
import { useKemudiMe } from '@/lib/kemudi-ai/skills'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import {
  currentSprint,
  type Health,
  health,
  LEVEL_ORDER,
  LEVELS,
  type Level,
  SLIP,
  type SprintProgress,
} from './health'
import { ProjectFilter } from './project-filter'

const LEVEL_DOT: Record<Level, string> = {
  red: 'bg-destructive',
  amber: 'bg-warning',
  green: 'bg-success',
}

type Row = {
  project: PortfolioProject
  signals: PortfolioSignals | undefined
  sprint: SprintProgress | null
  health: Health
}

/** The superadmin's helicopter view over every project. */
export function PortfolioPage() {
  const { t } = useTranslation(['portfolio', 'shell'])
  const me = useKemudiMe()
  const allowed = !!me.data?.superadmin

  return (
    <>
      <AppHeader crumbs={[{ label: t('shell:nav.portfolio') }]} />
      <Main width='table'>
        {me.isPending ? (
          <Skeleton className='h-40 w-full' />
        ) : !allowed ? (
          <div className='rounded-lg border border-dashed p-10 text-center'>
            <p className='font-medium'>{t('title')}</p>
            <p className='mt-1 text-sm text-muted-foreground'>
              {t('superadminOnly')}
            </p>
          </div>
        ) : (
          <PortfolioBody partial={!me.data?.is_superuser} />
        )}
      </Main>
    </>
  )
}

function PortfolioBody({ partial }: { partial: boolean }) {
  const { t } = useTranslation('portfolio')
  const f = useFormat()
  const projects = useAllProjects()
  const portfolio = usePortfolio()
  const setExcluded = useSetExcluded()
  const [only, setOnly] = useState<Level | null>(null)

  const excluded = useMemo(
    () => new Set(portfolio.data?.excluded ?? []),
    [portfolio.data?.excluded]
  )
  const included = useMemo(
    () => (projects.data ?? []).filter((p) => !excluded.has(p.slug)),
    [projects.data, excluded]
  )
  const sprints = useOpenSprints(included.map((p) => p.id))
  // eslint-disable-next-line react-hooks/exhaustive-deps -- re-read the clock on each refresh
  const now = useMemo(() => new Date(), [portfolio.dataUpdatedAt])

  const rows: Row[] = useMemo(
    () =>
      included
        .map((project) => {
          const signals = portfolio.data?.projects[project.slug]
          const sprint = currentSprint(sprints.byProject.get(project.id), now)
          return {
            project,
            signals,
            sprint,
            health: health(signals, sprint, portfolio.data?.warn_at),
          }
        })
        .sort(
          (a, b) =>
            LEVEL_ORDER[a.health.level] - LEVEL_ORDER[b.health.level] ||
            b.health.reasons.length - a.health.reasons.length ||
            a.project.name.localeCompare(b.project.name)
        ),
    [included, portfolio.data, sprints.byProject, now]
  )

  if (projects.isPending || portfolio.isPending)
    return (
      <div className='space-y-3'>
        <Skeleton className='h-8 w-64' />
        <Skeleton className='h-24 w-full' />
        <Skeleton className='h-64 w-full' />
      </div>
    )
  if (projects.isError || portfolio.isError)
    return (
      <p className='text-sm'>
        {t('loadFailed')}{' '}
        <button
          className='underline underline-offset-4'
          onClick={() => {
            projects.refetch()
            portfolio.refetch()
          }}
        >
          {t('refresh')}
        </button>
      </p>
    )

  const all = projects.data
  const counts = { red: 0, amber: 0, green: 0 }
  for (const r of rows) counts[r.health.level]++
  const visible = only ? rows.filter((r) => r.health.level === only) : rows

  return (
    <div className='grid gap-6'>
      <div className='flex flex-wrap items-end justify-between gap-3'>
        <div>
          <h1 className='text-2xl font-semibold tracking-tight'>
            {t('title')}
          </h1>
          <p className='mt-1 max-w-2xl text-sm text-muted-foreground'>
            {t('intro')}
          </p>
        </div>
        <div className='flex items-center gap-2'>
          <span className='text-xs text-muted-foreground'>
            {t('updated', { time: f.timeAgo(portfolio.data.generated_at) })}
          </span>
          <Button
            variant='ghost'
            size='icon'
            className='size-8'
            aria-label={t('refresh')}
            onClick={() => {
              portfolio.refetch()
              projects.refetch()
            }}
          >
            <RefreshCw className={cn(portfolio.isFetching && 'animate-spin')} />
          </Button>
          <ProjectFilter
            projects={all}
            excluded={excluded}
            onChange={(next) => setExcluded.mutate(next)}
          />
        </div>
      </div>

      {partial && (
        <p className='rounded-lg border p-3 text-sm text-muted-foreground'>
          {t('partialCoverage')}
        </p>
      )}

      <Kpis
        rows={rows}
        excluded={all.length - included.length}
        counts={counts}
        only={only}
        setOnly={setOnly}
        recentDays={portfolio.data.recent_days}
      />

      {included.length === 0 ? (
        <div className='rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground'>
          {t('empty')}
        </div>
      ) : visible.length === 0 ? (
        <div className='rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground'>
          {t('noneVisible')}
        </div>
      ) : (
        <PortfolioTable rows={visible} sprintsPending={sprints.pending} />
      )}

      <details className='text-sm text-muted-foreground'>
        <summary className='cursor-pointer font-medium text-foreground'>
          {t('rules.title')}
        </summary>
        <ul className='mt-2 grid gap-1'>
          {LEVELS.map((l) => (
            <li key={l} className='flex gap-2'>
              <span
                className={cn(
                  'mt-1.5 size-2 shrink-0 rounded-full',
                  LEVEL_DOT[l]
                )}
              />
              {t(`rules.${l}`)}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function Kpis({
  rows,
  excluded,
  counts,
  only,
  setOnly,
  recentDays,
}: {
  rows: Row[]
  excluded: number
  counts: Record<Level, number>
  only: Level | null
  setOnly: (l: Level | null) => void
  recentDays: number
}) {
  const { t } = useTranslation('portfolio')
  const f = useFormat()
  let value = 0
  let priced = 0
  let crWaiting = 0
  let agreed = 0
  let agreedValue = 0
  let spend = 0
  let failed = 0
  for (const { signals: s } of rows) {
    if (!s) continue
    if (s.contract.baseline_approved > 0) priced++
    value += s.contract.value_idr ?? 0
    crWaiting += s.cr.unreviewed
    agreed += s.cr.agreed_cr
    agreedValue += s.cr.agreed_cr_value_idr
    spend += s.usage.cost_idr
    failed += s.awak.failed_recent
  }

  return (
    <dl className='grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2 lg:grid-cols-5'>
      <Kpi
        label={t('kpi.projects')}
        value={f.number(rows.length)}
        detail={excluded ? t('kpi.projectsDetail', { excluded }) : undefined}
      />
      <div className='grid content-start gap-1.5 bg-card p-4'>
        <dt className='text-xs text-muted-foreground'>{t('kpi.health')}</dt>
        <dd className='flex flex-wrap gap-1.5'>
          {LEVELS.map((l) => {
            const active = only === l
            return (
              <button
                key={l}
                type='button'
                aria-pressed={active}
                title={
                  active
                    ? t('showAll')
                    : t('showOnly', { level: t(`levels.${l}`) })
                }
                onClick={() => setOnly(active ? null : l)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium tabular-nums transition-colors hover:bg-accent',
                  active && 'border-foreground/40 bg-accent'
                )}
              >
                <span className={cn('size-1.5 rounded-full', LEVEL_DOT[l])} />
                {counts[l]} {t(`levels.${l}`)}
              </button>
            )
          })}
        </dd>
      </div>
      <Kpi
        label={t('kpi.contractValue')}
        value={f.rupiah(value)}
        detail={t('kpi.contractValueDetail', { count: priced })}
      />
      <Kpi
        label={t('kpi.crWaiting')}
        value={f.number(crWaiting)}
        detail={t('kpi.crWaitingDetail', {
          agreed,
          value: f.rupiah(agreedValue),
        })}
        tone={crWaiting > 0 ? 'amber' : undefined}
      />
      <Kpi
        label={t('kpi.awakSpend')}
        value={f.rupiah(spend)}
        detail={t('kpi.awakSpendDetail', { count: failed, days: recentDays })}
        tone={failed > 0 ? 'red' : undefined}
      />
    </dl>
  )
}

function Kpi({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string
  detail?: string
  tone?: 'red' | 'amber'
}) {
  return (
    <div className='grid content-start gap-1 bg-card p-4'>
      <dt className='flex items-center gap-1.5 text-xs text-muted-foreground'>
        {tone && (
          <span className={cn('size-1.5 rounded-full', LEVEL_DOT[tone])} />
        )}
        {label}
      </dt>
      <dd className='text-base font-semibold tabular-nums'>{value}</dd>
      {detail && <dd className='text-xs text-muted-foreground'>{detail}</dd>}
    </div>
  )
}

function PortfolioTable({
  rows,
  sprintsPending,
}: {
  rows: Row[]
  sprintsPending: boolean
}) {
  const { t } = useTranslation('portfolio')
  const cols = [
    'project',
    'health',
    'sprint',
    'contract',
    'scope',
    'awak',
    'spend',
    'activity',
  ] as const
  return (
    <div className='overflow-x-auto rounded-lg border bg-card'>
      <table className='w-full min-w-[1100px] text-sm'>
        <thead>
          <tr className='border-b text-xs text-muted-foreground'>
            {cols.map((c) => (
              <th
                key={c}
                scope='col'
                className={cn(
                  'px-3 py-2 text-start font-medium',
                  c === 'spend' && 'text-end'
                )}
              >
                {t(`cols.${c}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <PortfolioRow
              key={r.project.id}
              row={r}
              sprintsPending={sprintsPending}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PortfolioRow({
  row: { project, signals: s, sprint, health: h },
  sprintsPending,
}: {
  row: Row
  sprintsPending: boolean
}) {
  const { t } = useTranslation('portfolio')
  const f = useFormat()
  const shownReasons = h.reasons.slice(0, 2)
  const moreReasons = h.reasons.slice(2)

  return (
    <tr className='border-b align-top last:border-b-0'>
      <td className='px-3 py-2.5'>
        <Link
          to='/p/$slug'
          params={{ slug: project.slug }}
          className='font-medium hover:underline'
        >
          {project.name}
        </Link>
        <div className='text-xs text-muted-foreground'>
          {project.slug}
          {project.is_private && <> · {t('private')}</>}
        </div>
      </td>

      <td className='px-3 py-2.5'>
        <span className='inline-flex items-center gap-1.5 rounded-md border bg-card px-2 py-0.5 text-xs font-medium whitespace-nowrap'>
          <span className={cn('size-1.5 rounded-full', LEVEL_DOT[h.level])} />
          {t(`levels.${h.level}`)}
        </span>
        {shownReasons.length > 0 && (
          <ul className='mt-1 grid max-w-56 gap-0.5 text-xs text-muted-foreground'>
            {shownReasons.map((r) => (
              <li key={r.key}>{t(`reasons.${r.key}`, r.values ?? {})}</li>
            ))}
            {moreReasons.length > 0 && (
              <li>
                <Tooltip>
                  <TooltipTrigger className='underline decoration-dotted underline-offset-2'>
                    {t('reasons.more', { count: moreReasons.length })}
                  </TooltipTrigger>
                  <TooltipContent>
                    <ul className='grid gap-0.5'>
                      {moreReasons.map((r) => (
                        <li key={r.key}>
                          {t(`reasons.${r.key}`, r.values ?? {})}
                        </li>
                      ))}
                    </ul>
                  </TooltipContent>
                </Tooltip>
              </li>
            )}
          </ul>
        )}
      </td>

      <td className='px-3 py-2.5'>
        {sprint ? (
          <SprintCell sprint={sprint} />
        ) : sprintsPending ? (
          <Skeleton className='h-8 w-36' />
        ) : (
          <span className='text-muted-foreground'>{t('sprint.none')}</span>
        )}
      </td>

      <td className='px-3 py-2.5'>
        {!s?.contract.exists ? (
          <span className='text-muted-foreground'>{t('contract.none')}</span>
        ) : s.contract.baseline_approved > 0 ? (
          <>
            <Link
              to='/p/$slug/contract'
              params={{ slug: project.slug }}
              className='hover:underline'
            >
              {t('contract.approved', { number: s.contract.baseline_approved })}
            </Link>
            <div className='text-xs text-muted-foreground tabular-nums'>
              {s.contract.value_idr != null
                ? f.rupiah(s.contract.value_idr)
                : t('contract.unpriced')}
            </div>
          </>
        ) : (
          <span>{t('contract.draft')}</span>
        )}
      </td>

      <td className='px-3 py-2.5'>
        {!s || s.cr.total === 0 ? (
          <span className='text-muted-foreground'>{t('scope.none')}</span>
        ) : (
          <>
            <div className='tabular-nums'>
              {t('scope.candidates', { count: s.cr.cr_candidate })}
            </div>
            <div className='text-xs text-muted-foreground tabular-nums'>
              {s.cr.unreviewed > 0 &&
                t('scope.toReview', { count: s.cr.unreviewed })}
              {s.cr.unreviewed > 0 && s.cr.agreed_cr_value_idr > 0 && ' · '}
              {s.cr.agreed_cr_value_idr > 0 &&
                t('scope.agreedValue', {
                  value: f.rupiah(s.cr.agreed_cr_value_idr),
                })}
            </div>
          </>
        )}
      </td>

      <td className='px-3 py-2.5'>
        {!s?.awak.enabled ? (
          <span className='text-muted-foreground'>{t('awak.off')}</span>
        ) : (
          <>
            <div className='tabular-nums'>
              {s.awak.running + s.awak.queued > 0
                ? t('awak.active', {
                    running: s.awak.running,
                    queued: s.awak.queued,
                  })
                : t('awak.idle')}
            </div>
            {s.awak.failed_recent > 0 && (
              <div className='text-xs text-destructive tabular-nums'>
                {t('awak.failed', { count: s.awak.failed_recent })}
              </div>
            )}
          </>
        )}
      </td>

      <td className='px-3 py-2.5 text-end'>
        {!s || (s.usage.tokens === 0 && !s.usage.budget_tokens) ? (
          <span className='text-muted-foreground'>—</span>
        ) : (
          <>
            <div className='tabular-nums'>{f.rupiah(s.usage.cost_idr)}</div>
            <div className='text-xs text-muted-foreground tabular-nums'>
              {s.usage.used_ratio != null
                ? t('spend.budget', {
                    pct: Math.round(s.usage.used_ratio * 100),
                  })
                : t('spend.noBudget')}
            </div>
          </>
        )}
      </td>

      <td className='px-3 py-2.5 text-xs whitespace-nowrap text-muted-foreground'>
        {f.timeAgo(project.modified_date)}
      </td>
    </tr>
  )
}

/** Points done against time gone, on one bar: the tick is "where we
 * should be", the fill is where we are. */
function SprintCell({ sprint }: { sprint: SprintProgress }) {
  const { t } = useTranslation('portfolio')
  const f = useFormat()
  const elapsed = Math.round(sprint.elapsed * 100)
  const done = sprint.done === null ? null : Math.round(sprint.done * 100)
  const behind = done !== null && sprint.elapsed - (sprint.done ?? 0) > SLIP
  return (
    <div className='grid w-44 gap-1'>
      <div className='truncate'>{sprint.sprint.name}</div>
      <div
        className='relative h-1.5 rounded-full bg-muted'
        role='img'
        aria-label={
          done === null
            ? t('sprint.noPoints', { elapsed })
            : t('sprint.progress', { done, elapsed })
        }
      >
        {done !== null && (
          <div
            className={cn(
              'h-full rounded-full',
              behind ? 'bg-warning' : 'bg-success'
            )}
            style={{ width: `${done}%` }}
          />
        )}
        <div
          className='absolute -top-0.5 h-2.5 w-px bg-foreground/60'
          style={{ left: `${elapsed}%` }}
        />
      </div>
      <div className='text-xs text-muted-foreground tabular-nums'>
        {done === null
          ? t('sprint.noPoints', { elapsed })
          : t('sprint.progress', { done, elapsed })}
      </div>
      <div className='text-xs text-muted-foreground'>
        {t('sprint.ends', { date: f.date(sprint.sprint.estimated_finish) })}
      </div>
    </div>
  )
}
