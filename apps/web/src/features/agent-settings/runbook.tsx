import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { CircleAlert, FileCode2, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  runbookErrors,
  useRunbook,
  useSaveRunbook,
  type Runbook,
  type RunbookApp,
  type RunbookService,
  type RunbookState,
} from '@/lib/kemudi-ai/agent'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'

/** What a new runbook starts from in the editor. */
const EMPTY_RUNBOOK: Runbook = { apps: [], services: [], env: [] }

/** Project settings → Agent → Runbook: read for members, Edit JSON for admins. */
export function RunbookCard({
  slug,
  canEdit,
}: {
  slug: string
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const query = useRunbook(slug)
  const [editing, setEditing] = useState(false)

  if (query.isPending) return <Skeleton className='h-24 w-full' />
  if (query.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('runbook.unavailable')}
      </p>
    )

  return (
    <>
      <RunbookView
        state={query.data}
        canEdit={canEdit}
        onEdit={() => setEditing(true)}
      />
      {canEdit && (
        <RunbookEditor
          slug={slug}
          runbook={query.data.runbook}
          open={editing}
          onOpenChange={setEditing}
        />
      )}
    </>
  )
}

export function RunbookView({
  state,
  canEdit,
  onEdit,
}: {
  state: RunbookState
  canEdit: boolean
  onEdit: () => void
}) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const rb = state.runbook

  if (!rb)
    return (
      <div className='grid justify-items-start gap-2 rounded-lg border border-dashed px-4 py-5'>
        <p className='text-sm font-medium'>{t('runbook.empty.title')}</p>
        <p className='max-w-prose text-sm text-muted-foreground'>
          {t('runbook.empty.body')}
        </p>
        <p className='max-w-prose text-sm text-muted-foreground'>
          {canEdit ? t('runbook.empty.admin') : t('runbook.empty.member')}
        </p>
        {canEdit && (
          <Button size='sm' variant='outline' className='mt-1' onClick={onEdit}>
            <FileCode2 />
            {t('runbook.paste')}
          </Button>
        )}
      </div>
    )

  const apps = Array.isArray(rb.apps) ? rb.apps : []
  const services = Array.isArray(rb.services) ? rb.services : []
  const env = Array.isArray(rb.env) ? rb.env : []

  return (
    <div className='grid gap-5'>
      <div className='flex flex-wrap items-center justify-between gap-x-6 gap-y-2'>
        <p className='text-xs text-muted-foreground'>
          {state.approved_by && state.approved_at
            ? t('runbook.approved', {
                version: state.version,
                who: state.approved_by,
                when: f.date(state.approved_at, 'dateTime'),
              })
            : t('runbook.version', { version: state.version })}
        </p>
        {canEdit && (
          <Button size='sm' variant='outline' onClick={onEdit}>
            <FileCode2 />
            {t('runbook.editJson')}
          </Button>
        )}
      </div>

      <Group title={t('runbook.apps.title')} count={apps.length}>
        {apps.map((app, i) => (
          <AppRow key={`${app.name}-${i}`} app={app} />
        ))}
      </Group>

      <Group title={t('runbook.services.title')} count={services.length}>
        {services.map((s, i) => (
          <ServiceRow
            key={`${s.name}-${i}`}
            service={s}
            isQa={rb.qa?.service === s.name}
            qaEnv={rb.qa?.service === s.name ? (rb.qa.env ?? []) : []}
            seed={rb.seed?.service === s.name ? rb.seed.command : null}
          />
        ))}
      </Group>

      <Group title={t('runbook.env.title')} count={env.length}>
        {env.map((e, i) => (
          <li
            key={`${e.name}-${i}`}
            className='grid gap-0.5 px-3 py-2 sm:grid-cols-[minmax(10rem,auto)_minmax(0,1fr)] sm:gap-4'
          >
            <span className='flex flex-wrap items-center gap-2'>
              <code className='font-mono text-xs font-medium'>{e.name}</code>
              {e.secret && (
                <span className='text-xs text-muted-foreground'>
                  {t('runbook.env.secret')}
                </span>
              )}
              {e.required && (
                <span className='text-xs text-muted-foreground'>
                  {t('runbook.env.required')}
                </span>
              )}
            </span>
            {e.description && (
              <span className='text-xs text-muted-foreground'>
                {e.description}
              </span>
            )}
          </li>
        ))}
      </Group>
    </div>
  )
}

function Group({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  const { t } = useTranslation('agent')
  return (
    <section className='grid gap-2'>
      <h3 className='text-sm font-semibold'>
        {title}{' '}
        <span className='font-normal text-muted-foreground tabular-nums'>
          {count}
        </span>
      </h3>
      {count === 0 ? (
        <p className='text-sm text-muted-foreground'>{t('runbook.none')}</p>
      ) : (
        <ul className='divide-y rounded-lg border text-sm'>{children}</ul>
      )}
    </section>
  )
}

/** One label and its command lines, e.g. "Checks" → tsc, lint. */
function Commands({
  rows,
}: {
  rows: [label: string, lines: string[] | undefined][]
}) {
  const shown = rows.filter(([, lines]) => lines && lines.length > 0)
  if (!shown.length) return null
  return (
    <dl className='grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[6rem_minmax(0,1fr)]'>
      {shown.map(([label, lines]) => (
        <div key={label} className='contents'>
          <dt className='text-muted-foreground'>{label}</dt>
          <dd className='grid min-w-0 gap-0.5'>
            {lines!.map((line, i) => (
              <code key={i} className='font-mono break-all'>
                {line}
              </code>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function AppRow({ app }: { app: RunbookApp }) {
  const { t } = useTranslation('agent')
  const envNames = Object.keys(app.env ?? {})
  const hasCommands = [app.install, app.checks, app.build, app.generated].some(
    (c) => Array.isArray(c) && c.length > 0
  )
  return (
    <li className='grid gap-2 px-3 py-2.5'>
      <div className='flex flex-wrap items-baseline gap-x-3 gap-y-1'>
        <span className='font-medium'>{app.name}</span>
        <span className='font-mono text-xs text-muted-foreground'>
          {app.repo}
          {' / '}
          {app.dir || t('runbook.apps.root')}
        </span>
        {app.run_in && (
          <Badge variant='outline' className='font-normal'>
            {t('runbook.apps.runIn', { target: app.run_in })}
          </Badge>
        )}
      </div>
      {hasCommands ? (
        <Commands
          rows={[
            [t('runbook.apps.install'), app.install],
            [t('runbook.apps.checks'), app.checks],
            [t('runbook.apps.build'), app.build],
            [t('runbook.apps.env'), envNames],
            [
              t('runbook.apps.generated'),
              Array.isArray(app.generated) ? app.generated : [],
            ],
          ]}
        />
      ) : (
        <p className='text-xs text-muted-foreground'>
          {t('runbook.apps.noCommands')}
        </p>
      )}
    </li>
  )
}

function ServiceRow({
  service: s,
  isQa,
  qaEnv,
  seed,
}: {
  service: RunbookService
  isQa: boolean
  qaEnv: string[]
  seed: string | null
}) {
  const { t } = useTranslation('agent')
  const envNames = Array.isArray(s.env) ? s.env : Object.keys(s.env ?? {})
  const source =
    s.kind === 'compose'
      ? [
          [s.repo, s.file].filter(Boolean).join(' / '),
          s.compose_services?.join(', '),
        ]
          .filter(Boolean)
          .join(' · ')
      : s.app
        ? t('runbook.services.ofApp', { app: s.app })
        : ''
  return (
    <li className='grid gap-2 px-3 py-2.5'>
      <div className='flex flex-wrap items-baseline gap-x-3 gap-y-1'>
        <span className='font-medium'>{s.name}</span>
        <Badge variant='secondary' className='font-normal'>
          {s.kind === 'process'
            ? t('runbook.services.kinds.process')
            : s.kind === 'compose'
              ? t('runbook.services.kinds.compose')
              : s.kind}
        </Badge>
        {isQa && (
          <Badge variant='outline' className='font-normal'>
            {t('runbook.services.qaTarget')}
          </Badge>
        )}
        {source && (
          <span className='font-mono text-xs text-muted-foreground'>
            {source}
          </span>
        )}
      </div>
      <Commands
        rows={[
          [t('runbook.services.command'), s.command ? [s.command] : []],
          [t('runbook.services.expose'), s.expose ? [s.expose] : []],
          [
            t('runbook.services.health'),
            [
              t('runbook.services.healthWithin', {
                path: s.health ?? '/',
                seconds: s.ready_timeout ?? 120,
              }),
            ],
          ],
          [t('runbook.services.seed'), seed ? [seed] : []],
          [t('runbook.apps.env'), envNames],
          [t('runbook.services.qaEnv'), qaEnv],
        ]}
      />
    </li>
  )
}

/** Paste or edit the whole runbook. Saving approves it as the saver. */
function RunbookEditor({
  slug,
  runbook,
  open,
  onOpenChange,
}: {
  slug: string
  runbook: Runbook | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation('agent')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='grid-rows-[auto_minmax(0,1fr)_auto] sm:max-w-2xl'>
        <DialogHeader>
          <DialogTitle>{t('runbook.editor.title')}</DialogTitle>
          <DialogDescription>
            {t('runbook.editor.description')}
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open, so every open starts from the saved one. */}
        <RunbookEditorBody
          slug={slug}
          runbook={runbook}
          onDone={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  )
}

function RunbookEditorBody({
  slug,
  runbook,
  onDone,
}: {
  slug: string
  runbook: Runbook | null
  onDone: () => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const save = useSaveRunbook(slug)
  const [text, setText] = useState(() =>
    JSON.stringify(runbook ?? EMPTY_RUNBOOK, null, 2)
  )
  const [errors, setErrors] = useState<string[]>([])
  const [jsonError, setJsonError] = useState<string | null>(null)

  const submit = () => {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      setErrors([])
      setJsonError(
        t('runbook.editor.invalidJson', {
          message: e instanceof Error ? e.message : String(e),
        })
      )
      return
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setErrors([])
      setJsonError(t('runbook.editor.notObject'))
      return
    }
    setJsonError(null)
    setErrors([])
    save.mutate(parsed as Runbook, {
      onSuccess: (saved) => {
        toast.success(t('runbook.saved', { version: saved.version }))
        onDone()
      },
      onError: (error) => setErrors(runbookErrors(error)),
    })
  }

  const invalid = jsonError !== null || errors.length > 0

  return (
    <form
      className='contents'
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <div className='grid min-h-0 gap-3'>
        <label htmlFor='runbook-json' className='sr-only'>
          {t('runbook.editor.label')}
        </label>
        <Textarea
          id='runbook-json'
          value={text}
          onChange={(e) => setText(e.target.value)}
          spellCheck={false}
          autoCapitalize='off'
          autoCorrect='off'
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? 'runbook-json-errors' : undefined}
          className='max-h-[50vh] min-h-64 overflow-auto font-mono text-xs leading-relaxed md:text-xs'
        />
        {jsonError && (
          <p
            id='runbook-json-errors'
            role='alert'
            className='text-sm text-destructive'
          >
            {jsonError}
          </p>
        )}
        {errors.length > 0 && (
          <Alert variant='destructive' id='runbook-json-errors' role='alert'>
            <CircleAlert />
            <AlertTitle>
              {t('runbook.editor.rejected', { count: errors.length })}
            </AlertTitle>
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
      </div>
      <DialogFooter>
        <Button type='button' variant='ghost' onClick={onDone}>
          {t('common:actions.cancel')}
        </Button>
        <Button type='submit' disabled={save.isPending}>
          {save.isPending && <Loader2 className='animate-spin' />}
          {t('runbook.editor.save')}
        </Button>
      </DialogFooter>
    </form>
  )
}
