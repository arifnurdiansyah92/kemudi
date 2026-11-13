import { useId, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { toLanguage } from '@/i18n'
import { AlertCircle, FileText, Info, Loader2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  agentError,
  useAgentSettings,
  useIntakeCreate,
  useIntakeDraft,
  type IntakeStory,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { useProject } from '@/features/project/use-project'
import { DraftList } from './draft-list'
import { draftsBody, toState, type DraftState } from './drafts'

const ACCEPT = '.pdf,.docx'
const isDocument = (f: File) => /\.(pdf|docx)$/i.test(f.name)

/** Project → Intake: text or a document in, editable story drafts out. */
export function Intake() {
  const { t, i18n } = useTranslation('agent')
  const project = useProject()
  const slug = project.slug
  const settings = useAgentSettings(slug)
  const draft = useIntakeDraft(slug)
  const create = useIntakeCreate(slug)

  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [lang, setLang] = useState<'id' | 'en'>(
    () => toLanguage(i18n.language) ?? 'id'
  )
  const [drafts, setDrafts] = useState<DraftState[] | null>(null)
  const [created, setCreated] = useState<IntakeStory[] | null>(null)

  const reset = () => {
    setDrafts(null)
    setCreated(null)
    draft.reset()
    create.reset()
  }

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug },
          },
          { label: t('intake.title') },
        ]}
      />
      <Main width='reading'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('intake.title')}
        </h1>
        <p className='mt-1 max-w-2xl text-sm text-muted-foreground'>
          {t('intake.intro')}
        </p>

        {settings.data && !settings.data.enabled && (
          <Alert className='mt-6'>
            <Info />
            <AlertTitle>{t('intake.agentOff.title')}</AlertTitle>
            <AlertDescription>
              <p>{t('intake.agentOff.body')}</p>
              {project.i_am_admin && (
                <Link
                  to='/p/$slug/settings/agent'
                  params={{ slug }}
                  className='font-medium text-primary underline-offset-4 hover:underline'
                >
                  {t('intake.agentOff.link')}
                </Link>
              )}
            </AlertDescription>
          </Alert>
        )}

        <div className='mt-8'>
          {created ? (
            <Created slug={slug} stories={created} onMore={reset} />
          ) : drafts ? (
            <DraftList
              drafts={drafts}
              onChange={(next) => {
                setDrafts(next)
                if (create.isError) create.reset()
              }}
              onDiscard={reset}
              creating={create.isPending}
              createError={create.error}
              onCreate={() =>
                // The drafts stay in state until the server says yes.
                create.mutate(draftsBody(drafts), {
                  onSuccess: (stories) => {
                    setCreated(stories)
                    setDrafts(null)
                    setText('')
                    setFile(null)
                  },
                })
              }
            />
          ) : (
            <SourceForm
              text={text}
              onText={setText}
              file={file}
              onFile={setFile}
              lang={lang}
              onLang={setLang}
              pending={draft.isPending}
              error={draft.error}
              onSubmit={() =>
                draft.mutate(
                  { text, lang, file },
                  { onSuccess: (out) => setDrafts(toState(out)) }
                )
              }
            />
          )}
        </div>
      </Main>
    </>
  )
}

function SourceForm({
  text,
  onText,
  file,
  onFile,
  lang,
  onLang,
  pending,
  error,
  onSubmit,
}: {
  text: string
  onText: (v: string) => void
  file: File | null
  onFile: (f: File | null) => void
  lang: 'id' | 'en'
  onLang: (v: 'id' | 'en') => void
  pending: boolean
  error: unknown
  onSubmit: () => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [badFile, setBadFile] = useState(false)
  const take = (f: File | undefined) => {
    if (!f) return
    setBadFile(!isDocument(f))
    if (isDocument(f)) onFile(f)
  }

  return (
    <form
      className='grid gap-5'
      onSubmit={(e) => {
        e.preventDefault()
        if (text.trim() || file) onSubmit()
      }}
    >
      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-text`}>{t('intake.source.text')}</Label>
        <Textarea
          id={`${id}-text`}
          value={text}
          rows={8}
          placeholder={t('intake.source.textPlaceholder')}
          className='field-sizing-content max-h-[60vh] min-h-40'
          disabled={pending}
          onChange={(e) => onText(e.target.value)}
        />
      </div>

      <div className='grid gap-1.5'>
        <span className='text-sm font-medium'>{t('intake.source.file')}</span>
        {file ? (
          <div className='flex items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm'>
            <FileText className='size-4 shrink-0 text-muted-foreground' />
            <span className='min-w-0 flex-1 truncate'>{file.name}</span>
            <Button
              type='button'
              variant='ghost'
              size='icon'
              className='size-7'
              disabled={pending}
              aria-label={t('intake.source.removeFile', { file: file.name })}
              onClick={() => onFile(null)}
            >
              <X />
            </Button>
          </div>
        ) : (
          <div
            className={cn(
              'rounded-lg border border-dashed px-4 py-5 text-center text-sm text-muted-foreground transition-colors',
              dragging && 'border-ring bg-accent/50 text-foreground'
            )}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              take(e.dataTransfer.files[0])
            }}
          >
            {t('intake.source.drop')}{' '}
            <button
              type='button'
              className='font-medium text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-none'
              onClick={() => input.current?.click()}
            >
              {t('intake.source.browse')}
            </button>
            <input
              ref={input}
              type='file'
              accept={ACCEPT}
              hidden
              data-testid='intake-file'
              onChange={(e) => {
                take(e.target.files?.[0])
                e.target.value = ''
              }}
            />
          </div>
        )}
        {badFile && (
          <p className='text-xs text-destructive'>
            {t('intake.source.badFile')}
          </p>
        )}
      </div>

      <div className='flex flex-wrap items-end gap-3'>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-lang`}>{t('intake.source.language')}</Label>
          <select
            id={`${id}-lang`}
            value={lang}
            disabled={pending}
            onChange={(e) => onLang(e.target.value as 'id' | 'en')}
            className='h-9 rounded-md border bg-background px-2 text-sm'
          >
            <option value='id'>{t('common:language.id')}</option>
            <option value='en'>{t('common:language.en')}</option>
          </select>
        </div>
        <Button type='submit' disabled={pending || (!text.trim() && !file)}>
          {pending && <Loader2 className='animate-spin' />}
          {t('intake.source.submit')}
        </Button>
      </div>

      {pending && (
        <p role='status' className='text-sm text-muted-foreground'>
          {t('intake.source.drafting')}
        </p>
      )}
      {error != null && !pending && (
        <Alert variant='destructive'>
          <AlertCircle />
          <AlertTitle>{t('intake.source.failed')}</AlertTitle>
          <AlertDescription>{agentError(error)}</AlertDescription>
        </Alert>
      )}
    </form>
  )
}

function Created({
  slug,
  stories,
  onMore,
}: {
  slug: string
  stories: IntakeStory[]
  onMore: () => void
}) {
  const { t } = useTranslation('agent')
  return (
    <section className='grid gap-4' aria-labelledby='intake-created'>
      <h2 id='intake-created' className='text-base font-semibold'>
        {t('intake.result.title', { count: stories.length })}
      </h2>
      <ul className='divide-y rounded-lg border bg-card'>
        {stories.map((s) => (
          <li
            key={s.id}
            className='grid gap-1 px-4 py-3 text-sm sm:grid-cols-[4rem_1fr_auto] sm:items-baseline sm:gap-3'
          >
            <Link
              to='/p/$slug/intake'
              params={{ slug }}
              search={{ ref: s.ref }}
              className='font-medium text-primary tabular-nums underline-offset-4 hover:underline'
            >
              #{s.ref}
            </Link>
            <span className='min-w-0'>{s.subject}</span>
            <span className='flex items-baseline gap-1.5 text-muted-foreground sm:justify-end'>
              <span
                aria-hidden
                className={cn(
                  'size-2 shrink-0 translate-y-[-1px] rounded-full',
                  s.ready ? 'bg-success' : 'bg-muted-foreground/50'
                )}
              />
              <span className='text-foreground'>
                {s.ready ? t('intake.result.ready') : t('intake.result.new')}
              </span>
              {!s.ready && s.reason && <span>· {s.reason}</span>}
            </span>
          </li>
        ))}
      </ul>
      <Button variant='outline' className='w-fit' onClick={onMore}>
        {t('intake.result.more')}
      </Button>
    </section>
  )
}
