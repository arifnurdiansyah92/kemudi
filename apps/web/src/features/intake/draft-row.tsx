import { Plus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  INTAKE_MAX_CRITERIA,
  intakeAreas,
  type IntakeArea,
  type IntakeDraftOut,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { SUBJECT_MIN, type DraftState } from './drafts'

/** Where the story will land, in words and a meaning-only dot. */
export function LandingPill({ draft }: { draft: DraftState }) {
  const { t } = useTranslation('agent')
  const [label, dot, reason] = draft.hold
    ? [t('intake.drafts.held'), 'bg-muted-foreground/50', '']
    : draft.edited
      ? [t('intake.drafts.rechecked'), 'bg-muted-foreground/50', '']
      : draft.ready
        ? [t('intake.drafts.ready'), 'bg-success', '']
        : [t('intake.drafts.waits'), 'bg-muted-foreground/50', draft.reason]
  return (
    <p className='flex min-w-0 items-baseline gap-1.5 text-sm'>
      <span
        aria-hidden
        className={cn('size-2 shrink-0 translate-y-[-1px] rounded-full', dot)}
      />
      <span className='shrink-0 font-medium'>{label}</span>
      {reason && (
        <span className='min-w-0 text-muted-foreground'>· {reason}</span>
      )}
    </p>
  )
}

export function DraftRow({
  n,
  draft,
  onChange,
  onRemove,
}: {
  n: number
  draft: DraftState
  onChange: (next: DraftState) => void
  onRemove: () => void
}) {
  const { t } = useTranslation('agent')
  const id = `draft-${draft.key}`
  const edit = (patch: Partial<IntakeDraftOut>) =>
    onChange({ ...draft, ...patch, edited: true })
  const short = draft.subject.trim().length < SUBJECT_MIN

  return (
    <li className='grid gap-4 px-4 py-5 sm:px-5'>
      <div className='flex flex-wrap items-center gap-x-4 gap-y-2'>
        <h3 className='text-sm font-semibold tabular-nums'>
          {t('intake.drafts.story', { n })}
        </h3>
        <div className='min-w-0 flex-1'>
          <LandingPill draft={draft} />
        </div>
        <Button
          variant='ghost'
          size='icon'
          className='-me-2 size-8'
          aria-label={t('intake.drafts.remove', { n })}
          onClick={onRemove}
        >
          <X />
        </Button>
      </div>

      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-subject`}>{t('intake.drafts.subject')}</Label>
        <Input
          id={`${id}-subject`}
          value={draft.subject}
          maxLength={200}
          aria-invalid={short || undefined}
          aria-describedby={short ? `${id}-subject-error` : undefined}
          onChange={(e) => edit({ subject: e.target.value })}
        />
        {short && (
          <p id={`${id}-subject-error`} className='text-xs text-destructive'>
            {t('intake.drafts.subjectShort')}
          </p>
        )}
      </div>

      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-description`}>
          {t('intake.drafts.description')}
        </Label>
        <Textarea
          id={`${id}-description`}
          value={draft.description}
          maxLength={5000}
          rows={3}
          className='field-sizing-content min-h-20'
          onChange={(e) => edit({ description: e.target.value })}
        />
      </div>

      <fieldset className='grid gap-2'>
        <legend className='mb-1.5 text-sm font-medium'>
          {t('intake.drafts.criteria')}
        </legend>
        {draft.criteria.length === 0 && (
          <p className='text-sm text-muted-foreground'>
            {t('intake.drafts.noCriteria')}
          </p>
        )}
        <ol className='grid gap-2'>
          {draft.criteria.map((c, i) => (
            <li key={i} className='flex items-center gap-2'>
              <span
                aria-hidden
                className='w-5 shrink-0 text-end text-xs text-muted-foreground tabular-nums'
              >
                {i + 1}.
              </span>
              <Input
                aria-label={t('intake.drafts.criterion', { n: i + 1 })}
                value={c}
                maxLength={500}
                className='h-8'
                onChange={(e) =>
                  edit({
                    criteria: draft.criteria.map((x, j) =>
                      j === i ? e.target.value : x
                    ),
                  })
                }
              />
              <Button
                variant='ghost'
                size='icon'
                className='size-7 shrink-0'
                aria-label={t('intake.drafts.removeCriterion', { n: i + 1 })}
                onClick={() =>
                  edit({ criteria: draft.criteria.filter((_, j) => j !== i) })
                }
              >
                <X />
              </Button>
            </li>
          ))}
        </ol>
        {draft.criteria.length < INTAKE_MAX_CRITERIA && (
          <Button
            variant='outline'
            size='sm'
            className='w-fit'
            onClick={() => edit({ criteria: [...draft.criteria, ''] })}
          >
            <Plus />
            {t('intake.drafts.addCriterion')}
          </Button>
        )}
      </fieldset>

      <div className='flex flex-wrap items-end gap-x-6 gap-y-3'>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-area`}>{t('intake.drafts.area')}</Label>
          <select
            id={`${id}-area`}
            value={draft.area}
            onChange={(e) => edit({ area: e.target.value as IntakeArea })}
            className='h-9 rounded-md border bg-background px-2 text-sm'
          >
            {intakeAreas.map((a) => (
              <option key={a} value={a}>
                {t(`intake.drafts.areas.${a}`)}
              </option>
            ))}
          </select>
        </div>
        <div className='flex h-9 items-center gap-2'>
          <Checkbox
            id={`${id}-hold`}
            checked={draft.hold}
            onCheckedChange={(v) => onChange({ ...draft, hold: v === true })}
          />
          <Label htmlFor={`${id}-hold`} className='font-normal'>
            {t('intake.drafts.hold')}
          </Label>
        </div>
      </div>
    </li>
  )
}
