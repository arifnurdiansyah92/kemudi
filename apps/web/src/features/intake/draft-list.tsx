import { AlertCircle, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { agentError, INTAKE_MAX_DRAFTS } from '@/lib/kemudi-ai/agent'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { DraftRow } from './draft-row'
import { SUBJECT_MIN, type DraftState } from './drafts'

export function DraftList({
  drafts,
  onChange,
  onCreate,
  onDiscard,
  creating,
  createError,
}: {
  drafts: DraftState[]
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
