import { AlertCircle, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  agentError,
  INTAKE_MAX_DRAFTS,
  type IntakeContext,
} from '@/lib/kemudi-ai/agent'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { DraftRow } from './draft-row'
import { SUBJECT_MIN, type DraftState } from './drafts'

export function DraftList({
  drafts,
  context,
  onChange,
  onCreate,
  onDiscard,
  creating,
  createError,
}: {
  drafts: DraftState[]
  context?: IntakeContext
  onChange: (drafts: DraftState[]) => void
  onCreate: () => void
  onDiscard: () => void
  creating: boolean
  createError: unknown
}) {
  const { t } = useTranslation('agent')
  const ready = drafts.filter((d) => d.ready && !d.hold && !d.edited).length
  const invalid = drafts.some((d) => d.subject.trim().length < SUBJECT_MIN)

  return (
    <section className='grid gap-4' aria-labelledby='intake-drafts'>
      <div>
        <h2 id='intake-drafts' className='text-base font-semibold'>
          {t('intake.drafts.title')}{' '}
          <span className='font-normal text-muted-foreground tabular-nums'>
            ({drafts.length})
          </span>
        </h2>
        {drafts.length > 0 && (
          <p className='mt-1 text-sm text-muted-foreground'>
            {t('intake.drafts.summary', {
              ready,
              waiting: drafts.length - ready,
            })}
          </p>
        )}
        {context && <ContextNote context={context} />}
      </div>

      {drafts.length === 0 ? (
        <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
          {t('intake.drafts.empty')}
        </p>
      ) : (
        <ol className='divide-y rounded-lg border bg-card'>
          {drafts.map((d, i) => (
            <DraftRow
              key={d.key}
              n={i + 1}
              draft={d}
              onChange={(next) =>
                onChange(drafts.map((x) => (x.key === d.key ? next : x)))
              }
              onRemove={() => onChange(drafts.filter((x) => x.key !== d.key))}
            />
          ))}
        </ol>
      )}

      {createError != null && (
        <Alert variant='destructive'>
          <AlertCircle />
          <AlertTitle>{t('intake.drafts.createFailed')}</AlertTitle>
          <AlertDescription>
            <p>{agentError(createError)}</p>
            <p>{t('intake.drafts.keptEdits')}</p>
          </AlertDescription>
        </Alert>
      )}

      <div className='flex flex-wrap gap-2'>
        {drafts.length > 0 && (
          <Button
            onClick={onCreate}
            disabled={creating || invalid || drafts.length > INTAKE_MAX_DRAFTS}
          >
            {creating && <Loader2 className='animate-spin' />}
            {t('intake.drafts.create', { count: drafts.length })}
          </Button>
        )}
        <Button variant='ghost' onClick={onDiscard} disabled={creating}>
          {t('intake.drafts.discard')}
        </Button>
      </div>
    </section>
  )
}

/** Which code the drafts were made against, so a PM knows how far to trust
 * the page and endpoint names in them. */
function ContextNote({ context }: { context: IntakeContext }) {
  const { t } = useTranslation('agent')
  return (
    <p className='mt-1 text-xs text-muted-foreground'>
      {context.repos.length > 0
        ? t('intake.drafts.context', {
            repos: context.repos.join(', '),
            count: context.files.length,
          })
        : t('intake.drafts.noContext')}
      {context.unavailable.length > 0 &&
        ' ' +
          t('intake.drafts.unavailable', {
            repos: context.unavailable.join(', '),
          })}
    </p>
  )
}
