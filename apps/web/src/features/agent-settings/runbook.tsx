import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { CircleAlert, FileCode2, Loader2, ScanSearch } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  isSetupLive,
  runbookErrors,
  useRunbook,
  useSaveRunbook,
  useSetupLatest,
  useStartSetup,
  type QaMode,
  type Runbook,
  type RunbookState,
} from '@/lib/kemudi-ai/agent'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { RunbookSummary } from './runbook-summary'
import { SetupAssistant } from './setup-assistant'

/** What a new runbook starts from in the editor. */
const EMPTY_RUNBOOK: Runbook = { apps: [], services: [], env: [] }

/** Project settings → Agent → Runbook: read for members; admins configure it
 * automatically (the Setup Assistant) or edit the JSON by hand. */
export function RunbookCard({
  slug,
  canEdit,
  qaMode,
}: {
  slug: string
  canEdit: boolean
  /** The project's current QA mode, to offer switching to Browser on approve. */
  qaMode?: QaMode
}) {
  const { t } = useTranslation('agent')
  const query = useRunbook(slug)
  const setup = useSetupLatest(slug)
  const start = useStartSetup(slug)
  const [editing, setEditing] = useState(false)

  if (query.isPending) return <Skeleton className='h-24 w-full' />
  if (query.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('runbook.unavailable')}
      </p>
    )

  const run = setup.data ?? null
  const live = isSetupLive(run)
  const configure = canEdit ? (
    <ConfigureButton
      busy={start.isPending}
      blocked={live}
      onClick={() => start.mutate()}
    />
  ) : null

  return (
    <>
      <RunbookView
        state={query.data}
        canEdit={canEdit}
        onEdit={() => setEditing(true)}
        configure={configure}
        assistant={
          run ? (
            <SetupAssistant
              slug={slug}
              run={run}
              canEdit={canEdit}
              qaMode={qaMode}
              onRetry={() => start.mutate()}
              retrying={start.isPending}
            />
          ) : null
        }
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

/** Starts the Setup Assistant; held back while a run is still going. */
function ConfigureButton({
  busy,
  blocked,
  onClick,
}: {
  busy: boolean
  blocked: boolean
  onClick: () => void
}) {
  const { t } = useTranslation('agent')
  return (
    <span className='flex flex-wrap items-center gap-x-3 gap-y-1'>
      <Button
        size='sm'
        disabled={busy || blocked}
        aria-describedby={blocked ? 'runbook-configure-hint' : undefined}
        onClick={onClick}
      >
        {busy ? <Loader2 className='animate-spin' /> : <ScanSearch />}
        {t('setup.configure')}
      </Button>
      {blocked && (
        <span
          id='runbook-configure-hint'
          className='text-xs text-muted-foreground'
        >
          {t('setup.configureBusy')}
        </span>
      )}
    </span>
  )
}

export function RunbookView({
  state,
  canEdit,
  onEdit,
  configure = null,
  assistant = null,
}: {
  state: RunbookState
  canEdit: boolean
  onEdit: () => void
  /** The admin's Configure automatically button. */
  configure?: React.ReactNode
  /** The Setup Assistant panel, when a run exists. */
  assistant?: React.ReactNode
}) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const rb = state.runbook

  if (!rb && !assistant)
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
          <div className='mt-1 flex flex-wrap items-center gap-2'>
            {configure}
            <Button size='sm' variant='outline' onClick={onEdit}>
              <FileCode2 />
              {t('runbook.paste')}
            </Button>
          </div>
        )}
      </div>
    )

  return (
    <div className='grid gap-5'>
      <div className='flex flex-wrap items-center justify-between gap-x-6 gap-y-2'>
        <p className='text-xs text-muted-foreground'>
          {!rb
            ? t('runbook.empty.title')
            : state.approved_by && state.approved_at
              ? t('runbook.approved', {
                  version: state.version,
                  who: state.approved_by,
                  when: f.date(state.approved_at, 'dateTime'),
                })
              : t('runbook.version', { version: state.version })}
        </p>
        {canEdit && (
          <div className='flex flex-wrap items-center gap-2'>
            {configure}
            <Button size='sm' variant='outline' onClick={onEdit}>
              <FileCode2 />
              {rb ? t('runbook.editJson') : t('runbook.paste')}
            </Button>
          </div>
        )}
      </div>

      {assistant}

      {rb && <RunbookSummary runbook={rb} />}
    </div>
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
