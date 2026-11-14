import { useCallback, useId, useState } from 'react'
import { useFormat } from '@/i18n/format'
import {
  ChevronRight,
  Circle,
  CircleAlert,
  CircleCheck,
  CircleDot,
  CircleSlash,
  CircleX,
  Loader2,
  RotateCcw,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  agentError,
  runbookErrors,
  useApproveSetup,
  useCancelSetup,
  useSetupEnv,
  useSetupScreenshot,
  type QaMode,
  type SetupConfirmEnv,
  type SetupMissingEnv,
  type SetupResources,
  type SetupRun,
  type SetupStep,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { RunbookSummary } from './runbook-summary'

/** The run's phases in order, as the timeline shows them. */
const PHASES = ['reading', 'proposing', 'env', 'proving', 'ready'] as const
type Phase = (typeof PHASES)[number]
type PhaseStatus = 'done' | 'current' | 'upcoming' | 'failed' | 'cancelled'

/** Where the run is, or where it stopped. */
function phaseOf(run: SetupRun): number {
  switch (run.state) {
    case 'queued':
      return 0
    case 'reading':
      return 1
    case 'needs_input':
      return 2
    case 'proving':
      return 3
    case 'ready':
    case 'approved':
      return 4
    default: {
      // failed or cancelled: the furthest phase it reached
      const p = run.proposal
      if (run.steps.length) return 3
      if (p.runbook) return run.missing_env.length ? 2 : 3
      return Object.keys(p.draft ?? {}).length ? 1 : 0
    }
  }
}

function phaseStatus(run: SetupRun, i: number, at: number): PhaseStatus {
  if (i < at || (i === at && run.state === 'ready')) return 'done'
  if (i > at) return 'upcoming'
  if (run.state === 'failed') return 'failed'
  if (run.state === 'cancelled') return 'cancelled'
  return 'current'
}

const preClass =
  'max-h-72 overflow-auto rounded-md bg-muted/60 px-3 py-2 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap'

/** Project settings → Agent → Runbook → the latest Configure automatically run. */
export function SetupAssistant({
  slug,
  run,
  canEdit,
  qaMode,
  onRetry,
  retrying,
}: {
  slug: string
  run: SetupRun
  canEdit: boolean
  qaMode?: QaMode
  onRetry: () => void
  retrying: boolean
}) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const cancel = useCancelSetup(slug)
  const titleId = useId()

  const footer = (
    <p className='flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground'>
      <span>
        {t('setup.startedBy', {
          who: run.created_by,
          when: f.date(run.created_at, 'dateTime'),
        })}
      </span>
      {run.cost_idr > 0 && (
        <span className='tabular-nums'>
          {t('setup.cost', { cost: f.rupiah(run.cost_idr) })}
        </span>
      )}
    </p>
  )

  if (
    run.state === 'approved' ||
    run.state === 'cancelled' ||
    run.state === 'superseded'
  ) {
    const approved = run.state === 'approved'
    return (
      <section
        aria-labelledby={titleId}
        className='grid gap-1 rounded-lg border px-4 py-3'
      >
        <h3
          id={titleId}
          className='flex items-center gap-2 text-sm font-medium'
        >
          {approved ? (
            <CircleCheck className='size-4 shrink-0 text-success' aria-hidden />
          ) : (
            <CircleSlash
              className='size-4 shrink-0 text-muted-foreground'
              aria-hidden
            />
          )}
          {t(`setup.${run.state}`)}
        </h3>
        {footer}
      </section>
    )
  }

  const cancellable = canEdit && (run.active || run.state === 'ready')

  return (
    <section
      aria-labelledby={titleId}
      aria-busy={run.active || undefined}
      className='grid gap-4 rounded-lg border p-4'
    >
      <div className='flex flex-wrap items-start justify-between gap-x-6 gap-y-2'>
        <div className='grid gap-0.5'>
          <h3
            id={titleId}
            className='flex flex-wrap items-center gap-2 text-sm font-semibold'
          >
            {t('setup.title')}
            {run.round > 1 && (
              <Badge variant='outline' className='font-normal tabular-nums'>
                {t('setup.round', { round: run.round, max: run.max_rounds })}
              </Badge>
            )}
          </h3>
          <p
            className='max-w-prose text-sm text-muted-foreground'
            role='status'
          >
            {run.state === 'reading' && run.round > 1
              ? t('setup.status.fixing')
              : t(`setup.status.${run.state}`)}
          </p>
        </div>
        {cancellable && run.state !== 'ready' && (
          <Button
            size='sm'
            variant='ghost'
            disabled={cancel.isPending}
            onClick={() => cancel.mutate(run.id)}
          >
            {cancel.isPending && <Loader2 className='animate-spin' />}
            {t('setup.cancel')}
          </Button>
        )}
      </div>

      <Timeline run={run} />

      {(run.state === 'queued' || run.state === 'reading') &&
        run.proposal.feedback && (
          <Disclosure label={t('setup.feedback')}>
            <pre className={preClass}>{run.proposal.feedback}</pre>
          </Disclosure>
        )}

      {run.state === 'needs_input' && (
        <div className='grid gap-5'>
          {run.confirm_env.length > 0 && (
            <ConfirmEnv
              slug={slug}
              runId={run.id}
              confirm={run.confirm_env}
              canEdit={canEdit}
            />
          )}
          {run.missing_env.length > 0 &&
            (canEdit ? (
              <EnvForm
                key={`${run.id}:${run.missing_env.map((m) => m.name).join(',')}`}
                slug={slug}
                runId={run.id}
                missing={run.missing_env}
              />
            ) : (
              <MissingEnvList missing={run.missing_env} />
            ))}
        </div>
      )}

      {run.state === 'failed' && (
        <Alert variant='destructive'>
          <CircleAlert />
          <AlertTitle>{t('setup.failed.title')}</AlertTitle>
          <AlertDescription className='grid gap-2'>
            <pre className={cn(preClass, 'w-full text-foreground')}>
              {run.error || t('setup.failed.noReason')}
            </pre>
          </AlertDescription>
        </Alert>
      )}

      {run.steps.length > 0 && <StepList steps={run.steps} />}

      {run.state === 'ready' && (
        <>
          {run.screenshot && <Screenshot slug={slug} runId={run.id} />}
          <Resources resources={run.resources} />
          {run.proposal.runbook && (
            <div className='grid gap-3'>
              <h4 className='text-sm font-semibold'>{t('setup.proposed')}</h4>
              <RunbookSummary runbook={run.proposal.runbook} />
            </div>
          )}
        </>
      )}

      {run.proposal.report &&
        (run.state === 'ready' || run.state === 'failed') && (
          <Disclosure label={t('setup.report')}>
            <pre className={preClass}>{run.proposal.report}</pre>
          </Disclosure>
        )}

      {run.state === 'ready' && canEdit && (
        <ApproveBar
          slug={slug}
          run={run}
          qaMode={qaMode}
          cancelling={cancel.isPending}
          onCancel={() => cancel.mutate(run.id)}
        />
      )}

      {run.state === 'failed' && canEdit && (
        <div>
          <Button size='sm' disabled={retrying} onClick={onRetry}>
            {retrying ? <Loader2 className='animate-spin' /> : <RotateCcw />}
            {t('setup.retry')}
          </Button>
        </div>
      )}

      {footer}
    </section>
  )
}

function Timeline({ run }: { run: SetupRun }) {
  const { t } = useTranslation('agent')
  const at = phaseOf(run)

  return (
    <ol className='grid gap-2 sm:grid-cols-5 sm:gap-3'>
      {PHASES.map((phase: Phase, i) => {
        const status = phaseStatus(run, i, at)
        return (
          <li
            key={phase}
            aria-current={status === 'current' ? 'step' : undefined}
            className={cn(
              'flex items-center gap-2 text-xs sm:grid sm:justify-items-start sm:gap-1.5 sm:border-t-2 sm:pt-2',
              status === 'done' && 'sm:border-success',
              status === 'current' && 'font-medium sm:border-primary',
              status === 'failed' && 'font-medium sm:border-destructive',
              (status === 'upcoming' || status === 'cancelled') &&
                'text-muted-foreground'
            )}
          >
            <PhaseIcon status={status} waiting={phase === 'env'} />
            <span>
              {t(`setup.phases.${phase}`)}
              <span className='sr-only'>
                {' '}
                ({t(`setup.phaseStatus.${status}`)})
              </span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function PhaseIcon({
  status,
  waiting,
}: {
  status: PhaseStatus
  waiting: boolean
}) {
  const cls = 'size-4 shrink-0'
  if (status === 'done')
    return <CircleCheck className={cn(cls, 'text-success')} aria-hidden />
  if (status === 'failed')
    return <CircleX className={cn(cls, 'text-destructive')} aria-hidden />
  if (status === 'cancelled') return <CircleSlash className={cls} aria-hidden />
  if (status === 'current')
    return waiting ? (
      <CircleDot className={cn(cls, 'text-primary')} aria-hidden />
    ) : (
      <Loader2 className={cn(cls, 'animate-spin text-primary')} aria-hidden />
    )
  return <Circle className={cn(cls, 'opacity-50')} aria-hidden />
}

/** A native disclosure: keyboard and screen readers get it for free. */
function Disclosure({
  label,
  meta,
  icon,
  children,
}: {
  label: React.ReactNode
  meta?: React.ReactNode
  icon?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <details className='group grid gap-2'>
      <summary className='flex cursor-pointer list-none items-center gap-2 rounded-sm text-sm outline-none select-none focus-visible:ring-[3px] focus-visible:ring-ring/50 [&::-webkit-details-marker]:hidden'>
        <ChevronRight
          className='size-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-90 motion-reduce:transition-none'
          aria-hidden
        />
        {icon}
        <span className='min-w-0 flex-1'>{label}</span>
        {meta}
      </summary>
      <div className='mt-2'>{children}</div>
    </details>
  )
}

function StepList({ steps }: { steps: SetupStep[] }) {
  const { t } = useTranslation('agent')
  return (
    <div className='grid gap-2'>
      <h4 className='text-sm font-semibold'>{t('setup.steps.title')}</h4>
      <ul className='divide-y rounded-lg border text-sm'>
        {steps.map((step, i) => (
          <li key={`${step.name}-${i}`} className='px-3 py-2'>
            <StepRow step={step} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function StepRow({ step }: { step: SetupStep }) {
  const { t } = useTranslation('agent')
  const status = step.ok ? 'ok' : step.red ? 'red' : 'failed'
  const gates = step.gates ?? []
  const passed = gates.filter((g) => g.ok).length
  const icon =
    status === 'ok' ? (
      <CircleCheck className='size-4 shrink-0 text-success' aria-hidden />
    ) : status === 'red' ? (
      <CircleAlert className='size-4 shrink-0 text-destructive' aria-hidden />
    ) : (
      <CircleX className='size-4 shrink-0 text-destructive' aria-hidden />
    )
  const meta = (
    <span
      className={cn(
        'shrink-0 text-xs tabular-nums',
        status === 'ok' ? 'text-muted-foreground' : 'text-destructive'
      )}
    >
      {gates.length > 0
        ? t('setup.steps.gates', { passed, count: gates.length })
        : t(`setup.steps.${status}`)}
    </span>
  )
  const label = <span className='font-mono text-xs'>{step.name}</span>

  if (!step.output.trim())
    return (
      <div className='flex items-center gap-2 ps-5.5'>
        {icon}
        <span className='min-w-0 flex-1'>{label}</span>
        {meta}
      </div>
    )
  return (
    <Disclosure label={label} icon={icon} meta={meta}>
      <pre className={preClass}>{step.output}</pre>
    </Disclosure>
  )
}

/** The PNG needs the auth header: fetched as a blob, shown through an object
 * URL that is revoked when the image goes away. */
function Screenshot({ slug, runId }: { slug: string; runId: number }) {
  const { t } = useTranslation('agent')
  const shot = useSetupScreenshot(slug, runId, true)
  const blob = shot.data
  const attach = useCallback(
    (img: HTMLImageElement | null) => {
      if (!img || !blob) return
      const url = URL.createObjectURL(blob)
      img.src = url
      return () => URL.revokeObjectURL(url)
    },
    [blob]
  )

  return (
    <figure className='grid gap-2'>
      <figcaption className='text-sm font-semibold'>
        {t('setup.screenshot.title')}
      </figcaption>
      {shot.isPending ? (
        <Skeleton className='aspect-video w-full max-w-xl' />
      ) : shot.isError || !blob ? (
        <p className='text-xs text-muted-foreground'>
          {t('setup.screenshot.unavailable')}
        </p>
      ) : (
        <img
          ref={attach}
          alt={t('setup.screenshot.alt')}
          className='max-h-96 w-full max-w-xl rounded-lg border object-contain object-top'
        />
      )}
    </figure>
  )
}

function Resources({ resources: r }: { resources: SetupResources }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const mb = (n: number | null | undefined) =>
    n == null
      ? '–'
      : t('setup.resources.mb', {
          mb: f.number(n, { maximumFractionDigits: 0 }),
        })
  const rows: { key: string; label: string; value: string }[] = [
    ...(r.compose ?? []).map((c, i) => ({
      key: `c-${i}`,
      label: `${c.service} · ${c.container}`,
      value:
        c.cpu_pct == null
          ? mb(c.mem_mb)
          : t('setup.resources.memCpu', {
              mem: mb(c.mem_mb),
              cpu: f.number(c.cpu_pct, { maximumFractionDigits: 1 }),
            }),
    })),
    ...(r.processes ?? []).map((p, i) => ({
      key: `p-${i}`,
      label: p.name,
      value: mb(p.rss_mb),
    })),
  ]
  if (r.runner_peak_mb != null)
    rows.push({
      key: 'runner',
      label: t('setup.resources.runner'),
      value: mb(r.runner_peak_mb),
    })
  if (r.total_mb == null && rows.length === 0) return null

  return (
    <div className='grid gap-2'>
      <h4 className='flex flex-wrap items-baseline gap-x-2 text-sm font-semibold'>
        {t('setup.resources.title')}
        {r.total_mb != null && (
          <span className='font-normal text-muted-foreground tabular-nums'>
            {t('setup.resources.total', { mem: mb(r.total_mb) })}
          </span>
        )}
      </h4>
      {rows.length > 0 && (
        <dl className='divide-y rounded-lg border text-xs'>
          {rows.map((row) => (
            <div
              key={row.key}
              className='flex flex-wrap justify-between gap-x-4 px-3 py-1.5'
            >
              <dt className='font-mono break-all'>{row.label}</dt>
              <dd className='text-muted-foreground tabular-nums'>
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

/** Members see which values the run waits for, never a form. */
function MissingEnvList({ missing }: { missing: SetupMissingEnv[] }) {
  const { t } = useTranslation('agent')
  return (
    <div className='grid gap-2'>
      <p className='text-sm text-muted-foreground'>
        {t('setup.env.memberWait')}
      </p>
      <ul className='divide-y rounded-lg border text-sm'>
        {missing.map((m) => (
          <li key={m.name} className='grid gap-0.5 px-3 py-2'>
            <code className='font-mono text-xs font-medium'>{m.name}</code>
            {m.description && (
              <span className='text-xs text-muted-foreground'>
                {m.description}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Saved vault values the proposed runbook hands to its commands. The agent
 * picked them, so the proof waits until an admin lets it use them. */
function ConfirmEnv({
  slug,
  runId,
  confirm,
  canEdit,
}: {
  slug: string
  runId: number
  confirm: SetupConfirmEnv[]
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const save = useSetupEnv(slug)
  const id = useId()
  const [problem, setProblem] = useState<string | null>(null)

  const submit = () => {
    setProblem(null)
    save.mutate(
      { runId, values: {}, confirm: true },
      {
        onSuccess: (run) =>
          toast.success(
            run.state === 'needs_input'
              ? t('setup.confirm.doneMore')
              : t('setup.env.saved')
          ),
        onError: (error) => setProblem(agentError(error)),
      }
    )
  }

  return (
    <div className='grid gap-3' role='group' aria-labelledby={`${id}-title`}>
      <div className='grid gap-0.5'>
        <h4 id={`${id}-title`} className='text-sm font-semibold'>
          {t('setup.confirm.title')}
        </h4>
        <p className='max-w-prose text-sm text-muted-foreground'>
          {canEdit ? t('setup.confirm.intro') : t('setup.confirm.memberWait')}
        </p>
      </div>
      <ul className='divide-y rounded-lg border text-sm'>
        {confirm.map((c) => (
          <li key={c.name} className='grid gap-1 px-3 py-2'>
            <div className='flex flex-wrap items-center gap-2'>
              <code className='font-mono text-xs font-medium break-all'>
                {c.name}
              </code>
              {c.secret && (
                <Badge variant='outline' className='font-normal'>
                  {t('setup.env.secret')}
                </Badge>
              )}
            </div>
            <p className='flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs text-muted-foreground'>
              <span>{t('setup.confirm.usedIn')}</span>
              {c.used_in.map((where) => (
                <code key={where} className='font-mono text-foreground'>
                  {where}
                </code>
              ))}
            </p>
          </li>
        ))}
      </ul>
      {problem && (
        <p role='alert' className='text-sm text-destructive'>
          {problem}
        </p>
      )}
      {canEdit && (
        <div className='flex flex-wrap items-center gap-x-3 gap-y-1'>
          <Button size='sm' disabled={save.isPending} onClick={submit}>
            {save.isPending && <Loader2 className='animate-spin' />}
            {t('setup.confirm.submit')}
          </Button>
          <span className='text-xs text-muted-foreground'>
            {t('setup.confirm.hint')}
          </span>
        </div>
      )}
    </div>
  )
}

/** The values the proof needs. They go to the vault and are never shown
 * again; a secret one stays write-only there too. */
function EnvForm({
  slug,
  runId,
  missing,
}: {
  slug: string
  runId: number
  missing: SetupMissingEnv[]
}) {
  const { t } = useTranslation('agent')
  const save = useSetupEnv(slug)
  const formId = useId()
  const [values, setValues] = useState<
    Record<string, { value: string; secret: boolean }>
  >(() =>
    Object.fromEntries(
      missing.map((m) => [m.name, { value: '', secret: m.secret }])
    )
  )
  const [problem, setProblem] = useState<string | null>(null)

  const set = (
    name: string,
    patch: Partial<{ value: string; secret: boolean }>
  ) => setValues((v) => ({ ...v, [name]: { ...v[name], ...patch } }))

  const submit = () => {
    // Only names the run still waits for; a value saved before is not sent again.
    const waiting = new Set(missing.map((m) => m.name))
    const filled = Object.fromEntries(
      Object.entries(values).filter(
        ([name, v]) => waiting.has(name) && v.value !== ''
      )
    )
    if (Object.keys(filled).length === 0)
      return setProblem(t('setup.env.noneFilled'))
    setProblem(null)
    save.mutate(
      { runId, values: filled },
      {
        onSuccess: (run) => {
          // saved: clear them, so a later submit sends only what is left
          setValues((v) =>
            Object.fromEntries(
              Object.entries(v).map(([name, entry]) => [
                name,
                name in filled ? { ...entry, value: '' } : entry,
              ])
            )
          )
          toast.success(
            run.state === 'needs_input' && run.missing_env.length > 0
              ? t('setup.env.savedMore', { count: run.missing_env.length })
              : run.state === 'needs_input'
                ? t('setup.env.savedConfirm')
                : t('setup.env.saved')
          )
        },
        onError: (error) => setProblem(agentError(error)),
      }
    )
  }

  return (
    <form
      className='grid gap-3'
      aria-describedby={`${formId}-intro`}
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <p id={`${formId}-intro`} className='text-sm text-muted-foreground'>
        {t('setup.env.intro')}
      </p>
      <ul className='divide-y rounded-lg border text-sm'>
        {missing.map((m) => {
          const id = `${formId}-${m.name}`
          const v = values[m.name] ?? { value: '', secret: m.secret }
          return (
            <li
              key={m.name}
              className='grid gap-2 px-3 py-3 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:gap-x-4'
            >
              <div className='grid content-start gap-0.5'>
                <Label htmlFor={id} className='font-mono text-xs break-all'>
                  {m.name}
                </Label>
                {m.description && (
                  <p
                    id={`${id}-desc`}
                    className='text-xs text-muted-foreground'
                  >
                    {m.description}
                  </p>
                )}
              </div>
              <div className='grid gap-2'>
                <Input
                  id={id}
                  type={v.secret ? 'password' : 'text'}
                  value={v.value}
                  maxLength={8192}
                  spellCheck={false}
                  autoComplete={v.secret ? 'new-password' : 'off'}
                  aria-describedby={m.description ? `${id}-desc` : undefined}
                  onChange={(e) => set(m.name, { value: e.target.value })}
                  className='font-mono text-xs'
                />
                <div className='flex items-center gap-2'>
                  <Switch
                    id={`${id}-secret`}
                    checked={v.secret}
                    aria-label={t('setup.env.secretFor', { name: m.name })}
                    onCheckedChange={(secret) => set(m.name, { secret })}
                  />
                  <Label
                    htmlFor={`${id}-secret`}
                    className='text-xs font-normal text-muted-foreground'
                  >
                    {t('setup.env.secret')}
                  </Label>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
      {problem && (
        <p role='alert' className='text-sm text-destructive'>
          {problem}
        </p>
      )}
      <div className='flex flex-wrap items-center gap-x-3 gap-y-1'>
        <Button type='submit' size='sm' disabled={save.isPending}>
          {save.isPending && <Loader2 className='animate-spin' />}
          {t('setup.env.submit')}
        </Button>
        <span className='text-xs text-muted-foreground'>
          {t('setup.env.writeOnly')}
        </span>
      </div>
    </form>
  )
}

function ApproveBar({
  slug,
  run,
  qaMode,
  cancelling,
  onCancel,
}: {
  slug: string
  run: SetupRun
  qaMode?: QaMode
  cancelling: boolean
  onCancel: () => void
}) {
  const { t } = useTranslation('agent')
  const approve = useApproveSetup(slug)
  const hasQa = !!run.proposal.runbook?.qa?.service
  const offerBrowser = hasQa && qaMode !== 'browser'
  const [browser, setBrowser] = useState(offerBrowser)
  const [errors, setErrors] = useState<string[]>([])
  const checkId = useId()

  const submit = () => {
    setErrors([])
    approve.mutate(
      { runId: run.id, qaMode: offerBrowser && browser ? 'browser' : null },
      {
        onSuccess: (data) =>
          toast.success(
            t('setup.approvedToast', { version: data.runbook.version })
          ),
        onError: (error) => setErrors(runbookErrors(error)),
      }
    )
  }

  return (
    <div className='grid gap-3 border-t pt-4'>
      {offerBrowser && (
        <div className='flex items-start gap-3'>
          <Checkbox
            id={checkId}
            checked={browser}
            onCheckedChange={(on) => setBrowser(on === true)}
            aria-describedby={`${checkId}-hint`}
            className='mt-0.5'
          />
          <div className='grid gap-0.5'>
            <Label htmlFor={checkId}>{t('setup.approve.browser')}</Label>
            <p
              id={`${checkId}-hint`}
              className='max-w-prose text-xs text-muted-foreground'
            >
              {t('setup.approve.browserHint')}
            </p>
          </div>
        </div>
      )}
      {errors.length > 0 && (
        <Alert variant='destructive' role='alert'>
          <CircleAlert />
          <AlertTitle>{t('setup.approve.rejected')}</AlertTitle>
          <AlertDescription>
            <ul className='grid list-disc gap-1 ps-4 text-xs'>
              {errors.map((err, i) => (
                <li key={i} className='break-words'>
                  {err}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      <div className='flex flex-wrap items-center gap-2'>
        <Button
          size='sm'
          disabled={approve.isPending || cancelling}
          onClick={submit}
        >
          {approve.isPending && <Loader2 className='animate-spin' />}
          {t('setup.approve.submit')}
        </Button>
        <Button
          size='sm'
          variant='ghost'
          disabled={approve.isPending || cancelling}
          onClick={onCancel}
        >
          {cancelling && <Loader2 className='animate-spin' />}
          {t('setup.cancel')}
        </Button>
      </div>
    </div>
  )
}
