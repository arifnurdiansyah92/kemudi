import { useId, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import {
  AlertCircle,
  Copy,
  Download,
  Inbox,
  Info,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'
import { agentError } from '@/lib/kemudi-ai/agent'
import {
  isProductRunActive,
  isProductRunMissing,
  useDeleteProductRun,
  useProductRun,
  type ProductAgents,
  type ProductRun,
  type ProductSource,
} from '@/lib/kemudi-ai/product'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { setIntakePrefill } from '@/features/intake/prefill'
import { useProject } from '@/features/project/use-project'
import { Markdown } from '@/features/skills/markdown'
import { safeHref } from '@/features/skills/markdown-parse'
import {
  downloadText,
  reportFileName,
  suggestionsToRequirements,
} from './handoff'
import { useStageText } from './run-meta'
import { StatusBadge } from './run-status'

const suggestionFields = ['problem', 'proposal', 'value', 'evidence'] as const

/** One run: what was asked, how it is going, and the report once done. */
export function RunDetail({
  id,
  agents,
  onClose,
}: {
  id: number
  agents: ProductAgents | undefined
  /** Back to the new-run form. */
  onClose: () => void
}) {
  const { t } = useTranslation('agent')
  const project = useProject()
  const query = useProductRun(project.slug, id)

  if (query.isPending)
    return (
      <div className='grid gap-4' aria-busy='true'>
        <Skeleton className='h-4 w-32' />
        <Skeleton className='h-7 w-2/3' />
        <Skeleton className='h-40 w-full' />
      </div>
    )

  if (!query.data) {
    const missing = isProductRunMissing(query.error)
    return (
      <div className='grid justify-items-start gap-4'>
        <Alert variant={missing ? 'default' : 'destructive'}>
          {missing ? <Info /> : <AlertCircle />}
          <AlertTitle>
            {missing
              ? t('research.detail.notFoundTitle')
              : t('research.detail.loadFailed')}
          </AlertTitle>
          <AlertDescription>
            {missing
              ? t('research.detail.notFoundBody')
              : agentError(query.error)}
          </AlertDescription>
        </Alert>
        <Button variant='outline' onClick={onClose}>
          <Plus />
          {t('research.detail.new')}
        </Button>
      </div>
    )
  }

  const run = query.data
  const needsWeb =
    agents?.agents.find((a) => a.kind === run.kind)?.needs_web ?? false

  return (
    <article className='grid min-w-0 gap-6' aria-labelledby={`run-${id}-title`}>
      <RunHeader run={run} onClose={onClose} />

      {isProductRunActive(run) && <Working run={run} />}

      {run.status === 'failed' && (
        <Alert variant='destructive'>
          <AlertCircle />
          <AlertTitle>{t('research.detail.failedTitle')}</AlertTitle>
          <AlertDescription>
            {run.error || t('research.detail.failedFallback')}
          </AlertDescription>
        </Alert>
      )}

      {run.status === 'done' && (
        <>
          {needsWeb && !run.web && (
            <p className='flex gap-2 text-sm text-muted-foreground'>
              <Info aria-hidden className='mt-0.5 size-4 shrink-0' />
              {t('research.detail.noWebUsed')}
            </p>
          )}
          <section className='grid gap-3' aria-labelledby={`run-${id}-report`}>
            <h3 id={`run-${id}-report`} className='sr-only'>
              {t('research.detail.report')}
            </h3>
            {run.report.trim() ? (
              <Markdown
                source={run.report}
                className='rounded-lg border bg-card px-4 py-4 sm:px-6 sm:py-5'
              />
            ) : (
              <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
                {t('research.detail.emptyReport')}
              </p>
            )}
          </section>
          {run.suggestions.length > 0 && <Suggestions key={run.id} run={run} />}
          {run.sources.length > 0 && <Sources sources={run.sources} />}
        </>
      )}
    </article>
  )
}

function RunHeader({ run, onClose }: { run: ProductRun; onClose: () => void }) {
  const { t } = useTranslation(['agent', 'common'])
  const f = useFormat()
  const project = useProject()
  const username = useAuthStore((s) => s.session?.user.username)
  const del = useDeleteProductRun(project.slug)
  const [confirming, setConfirming] = useState(false)

  const kindLabel = t(`research.kinds.${run.kind}.label`)
  const title = run.title || kindLabel
  const canDelete = project.i_am_admin || run.created_by === username
  const running = run.status === 'running'
  const hasReport = run.status === 'done' && run.report.trim() !== ''

  const copy = () => {
    const done = navigator.clipboard?.writeText(run.report)
    if (!done) return void toast.error(t('research.detail.copyFailed'))
    done.then(
      () => toast.success(t('research.detail.copied')),
      () => toast.error(t('research.detail.copyFailed'))
    )
  }

  return (
    <header className='grid gap-4'>
      <div className='flex flex-wrap items-start justify-between gap-x-4 gap-y-2'>
        <div className='grid min-w-0 gap-1'>
          <p className='text-xs text-muted-foreground'>
            {kindLabel} <span className='tabular-nums'>#{run.id}</span>
          </p>
          <h2
            id={`run-${run.id}-title`}
            className='text-xl font-semibold tracking-tight break-words'
          >
            {title}
          </h2>
          <p className='flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground'>
            <StatusBadge status={run.status} className='text-foreground' />
            <span aria-hidden>·</span>
            <span>{t('research.detail.by', { who: run.created_by })}</span>
            <span aria-hidden>·</span>
            <time dateTime={run.created_at}>{f.timeAgo(run.created_at)}</time>
          </p>
        </div>
        <Button variant='outline' size='sm' onClick={onClose}>
          <Plus />
          {t('research.detail.new')}
        </Button>
      </div>

      <div className='grid gap-1 border-s-2 ps-3 text-sm'>
        <p className='text-xs font-medium text-muted-foreground'>
          {t('research.detail.brief')}
        </p>
        <p
          className={cn(
            'break-words whitespace-pre-wrap',
            !run.brief && 'text-muted-foreground'
          )}
        >
          {run.brief || t('research.detail.noBrief')}
        </p>
        {run.kind === 'report' && run.options.days != null && (
          <p className='text-xs text-muted-foreground'>
            {t('research.detail.period', { count: run.options.days })}
          </p>
        )}
        {run.kind === 'features' && run.options.based_on != null && (
          <p className='text-xs text-muted-foreground'>
            {t('research.detail.basedOn', { id: run.options.based_on })}
          </p>
        )}
      </div>

      {(hasReport || canDelete) && (
        <div className='flex flex-wrap items-center gap-2'>
          {hasReport && (
            <>
              <Button variant='outline' size='sm' onClick={copy}>
                <Copy />
                {t('research.detail.copy')}
              </Button>
              <Button
                variant='outline'
                size='sm'
                onClick={() =>
                  downloadText(reportFileName(title, run.id), run.report)
                }
              >
                <Download />
                {t('research.detail.download')}
              </Button>
            </>
          )}
          {canDelete && (
            <>
              <Button
                variant='ghost'
                size='sm'
                className='text-destructive hover:text-destructive sm:ms-auto'
                disabled={running || del.isPending}
                aria-describedby={
                  running ? `run-${run.id}-delete-note` : undefined
                }
                onClick={() => setConfirming(true)}
              >
                <Trash2 />
                {t('research.detail.delete')}
              </Button>
              {running && (
                <p
                  id={`run-${run.id}-delete-note`}
                  className='w-full text-xs text-muted-foreground sm:text-end'
                >
                  {t('research.detail.deleteRunning')}
                </p>
              )}
            </>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        destructive
        title={t('research.detail.deleteTitle')}
        desc={t('research.detail.deleteBody', { title })}
        confirmText={t('common:actions.delete')}
        isLoading={del.isPending}
        handleConfirm={() =>
          del.mutate(run.id, {
            onSuccess: () => {
              toast.success(t('research.detail.deleted'))
              onClose()
            },
            onSettled: () => setConfirming(false),
          })
        }
      />
    </header>
  )
}

function Working({ run }: { run: ProductRun }) {
  const { t } = useTranslation('agent')
  const stage = useStageText()
  return (
    <div
      role='status'
      className='grid gap-1 rounded-lg border bg-card px-4 py-4 text-sm'
    >
      <p className='flex items-center gap-2 font-medium'>
        <Loader2
          aria-hidden
          className='size-4 shrink-0 text-muted-foreground motion-safe:animate-spin'
        />
        {stage(run)}
      </p>
      <p className='text-muted-foreground'>{t('research.detail.waiting')}</p>
    </div>
  )
}

/** The proposals of a `features` run; the picked ones go to Intake as text. */
function Suggestions({ run }: { run: ProductRun }) {
  const { t, i18n } = useTranslation('agent')
  const id = useId()
  const navigate = useNavigate()
  const { slug } = useProject()
  // Everything is picked until the reader unticks it.
  const [skipped, setSkipped] = useState<ReadonlySet<number>>(new Set())
  const total = run.suggestions.length
  const count = total - skipped.size

  const send = () => {
    // The labels follow the report's language, like the suggestions do.
    const label = i18n.getFixedT(run.lang, 'agent')
    setIntakePrefill(
      slug,
      suggestionsToRequirements(
        run.suggestions.filter((_, i) => !skipped.has(i)),
        {
          problem: label('research.suggestions.problem'),
          proposal: label('research.suggestions.proposal'),
        }
      )
    )
    void navigate({ to: '/p/$slug/intake', params: { slug } })
  }

  return (
    <section className='grid gap-4' aria-labelledby={`${id}-title`}>
      <div className='grid gap-1'>
        <h3 id={`${id}-title`} className='text-base font-semibold'>
          {t('research.suggestions.title')}{' '}
          <span className='font-normal text-muted-foreground tabular-nums'>
            ({total})
          </span>
        </h3>
        <p className='text-sm text-muted-foreground'>
          {t('research.suggestions.hint')}
        </p>
      </div>

      <ul className='grid gap-3'>
        {run.suggestions.map((s, i) => {
          const picked = !skipped.has(i)
          return (
            <li
              key={i}
              className={cn(
                'grid gap-3 rounded-lg border bg-card px-4 py-4 transition-colors',
                picked ? 'border-primary/60' : 'opacity-75'
              )}
            >
              <div className='flex items-start gap-3'>
                <Checkbox
                  id={`${id}-${i}`}
                  className='mt-0.5'
                  checked={picked}
                  onCheckedChange={(on) =>
                    setSkipped((prev) => {
                      const next = new Set(prev)
                      if (on === true) next.delete(i)
                      else next.add(i)
                      return next
                    })
                  }
                />
                <label
                  htmlFor={`${id}-${i}`}
                  className='min-w-0 flex-1 cursor-pointer text-sm font-semibold break-words'
                >
                  {s.title}
                </label>
              </div>
              <div className='flex flex-wrap gap-1.5 ps-7'>
                <Badge variant='secondary'>
                  {t(`research.suggestions.effort.${s.effort}`, {
                    defaultValue: s.effort,
                  })}
                </Badge>
                <Badge variant='outline'>
                  {t(`intake.drafts.areas.${s.area}`, { defaultValue: s.area })}
                </Badge>
              </div>
              <dl className='grid gap-2 ps-7 text-sm'>
                {suggestionFields.map(
                  (field) =>
                    s[field] && (
                      <div key={field} className='grid gap-0.5'>
                        <dt className='text-xs font-medium text-muted-foreground'>
                          {t(`research.suggestions.${field}`)}
                        </dt>
                        <dd className='break-words'>{s[field]}</dd>
                      </div>
                    )
                )}
              </dl>
            </li>
          )
        })}
      </ul>

      <div className='flex flex-wrap items-center gap-x-4 gap-y-2'>
        <Button onClick={send} disabled={count === 0}>
          <Inbox />
          {t('research.suggestions.send')}
        </Button>
        <Button
          variant='ghost'
          onClick={() =>
            setSkipped(
              count === total ? new Set(run.suggestions.keys()) : new Set()
            )
          }
        >
          {count === total
            ? t('research.suggestions.selectNone')
            : t('research.suggestions.selectAll')}
        </Button>
        <p className='text-sm text-muted-foreground tabular-nums'>
          {t('research.suggestions.selected', { count, total })}
        </p>
      </div>
    </section>
  )
}

function Sources({ sources }: { sources: ProductSource[] }) {
  const { t } = useTranslation('agent')
  const id = useId()
  return (
    <section className='grid gap-2' aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className='text-base font-semibold'>
        {t('research.detail.sources')}{' '}
        <span className='font-normal text-muted-foreground tabular-nums'>
          ({sources.length})
        </span>
      </h3>
      <ol className='grid list-decimal gap-1.5 ps-5 text-sm'>
        {sources.map((s, i) => {
          // Sources come from the open web: only http(s) becomes a link.
          const href = safeHref(s.url)
          return (
            <li key={i} className='break-words'>
              {href && /^https?:/i.test(href) ? (
                <a
                  href={href}
                  target='_blank'
                  rel='noopener noreferrer'
                  className='text-primary underline-offset-4 hover:underline'
                >
                  {s.title || s.url}
                </a>
              ) : (
                <span>{s.title || s.url}</span>
              )}
              {s.title && (
                <span className='block text-xs break-all text-muted-foreground'>
                  {s.url}
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </section>
  )
}
