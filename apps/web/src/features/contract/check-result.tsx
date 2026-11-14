import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Check, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  scopeLabels,
  type CrCheck,
  type CrVerdict,
  type ScopeLabel,
} from '@/lib/kemudi-ai/queries'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ScopeChip } from './scope-label'

/**
 * One CR check: the AI's label and why, the baseline items it cites, effort
 * in person-days (indicative) and, when the project shows prices, Rupiah.
 * Admins record a verdict; a wrong label should be cheap to dismiss.
 */
export function CheckResult({
  check,
  canReview,
  onVerdict,
  busy = false,
}: {
  check: CrCheck
  canReview: boolean
  onVerdict: (v: CrVerdict) => void
  busy?: boolean
}) {
  const { t } = useTranslation('contract')
  const format = useFormat()
  const effort = Object.entries(check.effort_days)
  const showEffort = check.label !== 'in_baseline' && effort.length > 0

  return (
    <div className='grid gap-3 text-sm'>
      <div className='flex flex-wrap items-center gap-2'>
        <ScopeChip label={check.label} />
        <span className='text-xs text-muted-foreground'>
          {t('check.suggestion', { version: check.baseline_number })}
        </span>
      </div>
      <p>{check.reasoning}</p>
      {check.question && (
        <p className='text-muted-foreground'>
          {t('check.question', { question: check.question })}
        </p>
      )}
      {(check.cited.length > 0 || check.clause) && (
        <div>
          <p className='text-xs font-medium text-muted-foreground'>
            {t('check.cited')}
          </p>
          {check.cited.length > 0 ? (
            <ul className='mt-1 grid gap-1'>
              {check.cited.map((c) => (
                <li key={c.ref}>
                  <span className='font-mono text-xs'>{c.ref}</span> {c.title}
                  {c.clauses.length > 0 && (
                    <span className='text-xs text-muted-foreground'>
                      {' '}
                      · {c.clauses.join('; ')}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className='mt-1 text-xs'>{check.clause}</p>
          )}
        </div>
      )}
      {(showEffort || check.price_idr) && (
        <dl className='flex flex-wrap gap-x-6 gap-y-1'>
          {showEffort && (
            <div>
              <dt className='text-xs text-muted-foreground'>
                {t('check.effort')}{' '}
                <span className='rounded border px-1 text-[0.65rem] tracking-wide uppercase'>
                  {t('check.indicative')}
                </span>
              </dt>
              <dd className='tabular-nums'>
                {t('check.days', {
                  days: format.number(check.effort_total_days),
                })}
                <span className='text-xs text-muted-foreground'>
                  {' '}
                  (
                  {effort
                    .map(([role, d]) => `${role} ${format.number(d)}`)
                    .join(', ')}
                  )
                </span>
              </dd>
            </div>
          )}
          {check.price_idr ? (
            <div>
              <dt className='text-xs text-muted-foreground'>
                {t('check.price')}
              </dt>
              <dd className='tabular-nums'>{format.rupiah(check.price_idr)}</dd>
            </div>
          ) : null}
        </dl>
      )}
      <p className='text-xs text-muted-foreground'>
        {t('check.checkedBy', {
          by: check.checked_by,
          date: format.date(check.checked_at, 'dateTime'),
          model: check.model,
        })}
      </p>
      <Verdict
        check={check}
        canReview={canReview}
        onVerdict={onVerdict}
        busy={busy}
      />
    </div>
  )
}

function Verdict({
  check,
  canReview,
  onVerdict,
  busy,
}: {
  check: CrCheck
  canReview: boolean
  onVerdict: (v: CrVerdict) => void
  busy: boolean
}) {
  const { t } = useTranslation(['contract', 'common'])
  const format = useFormat()
  const [disagreeing, setDisagreeing] = useState(false)
  const others = scopeLabels.filter((l) => l !== check.label)
  const [corrected, setCorrected] = useState<ScopeLabel | ''>('')
  const [note, setNote] = useState('')

  return (
    <div className='grid gap-2 border-t pt-3'>
      {check.verdict ? (
        <div className='text-xs'>
          <p>
            {t(check.verdict === 'agree' ? 'check.agreed' : 'check.disagreed', {
              by: check.decided_by,
              date: check.decided_at
                ? format.date(check.decided_at, 'dateTime')
                : '',
            })}
          </p>
          {check.corrected_label && (
            <p className='mt-1'>
              {t('check.correctedTo', {
                label: t(`labels.${check.corrected_label}`),
              })}
            </p>
          )}
          {check.verdict_note && (
            <p className='mt-1 text-muted-foreground'>{check.verdict_note}</p>
          )}
        </div>
      ) : (
        <p className='text-xs text-muted-foreground'>{t('check.pending')}</p>
      )}
      {canReview && !disagreeing && (
        <div className='flex gap-2'>
          <Button
            size='sm'
            variant={check.verdict === 'agree' ? 'default' : 'outline'}
            aria-pressed={check.verdict === 'agree'}
            disabled={busy}
            onClick={() => onVerdict({ verdict: 'agree' })}
          >
            <Check />
            {t('check.agree')}
          </Button>
          <Button
            size='sm'
            variant={check.verdict === 'disagree' ? 'destructive' : 'outline'}
            aria-pressed={check.verdict === 'disagree'}
            disabled={busy}
            onClick={() => {
              setCorrected(check.corrected_label ?? '')
              setNote(check.verdict_note)
              setDisagreeing(true)
            }}
          >
            <X />
            {t('check.disagree')}
          </Button>
        </div>
      )}
      {canReview && disagreeing && (
        <form
          className='grid gap-3 rounded-md border p-3'
          onSubmit={(e) => {
            e.preventDefault()
            onVerdict({
              verdict: 'disagree',
              corrected_label: corrected || null,
              note: note.trim(),
            })
            setDisagreeing(false)
          }}
        >
          <fieldset className='grid gap-1.5'>
            <legend className='mb-1.5 text-sm font-medium'>
              {t('check.correctLabel')}
            </legend>
            <div className='flex flex-wrap gap-x-4 gap-y-1'>
              {[...others, '' as const].map((l) => (
                <label key={l || 'none'} className='flex items-center gap-1.5'>
                  <input
                    type='radio'
                    name={`corrected-${check.id}`}
                    value={l}
                    checked={corrected === l}
                    onChange={() => setCorrected(l as ScopeLabel | '')}
                  />
                  {l ? t(`labels.${l}`) : t('check.noCorrection')}
                </label>
              ))}
            </div>
          </fieldset>
          <div className='grid gap-1.5'>
            <Label htmlFor={`verdict-note-${check.id}`}>
              {t('check.note')}
            </Label>
            <Textarea
              id={`verdict-note-${check.id}`}
              value={note}
              maxLength={2000}
              placeholder={t('check.notePlaceholder')}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <div className='flex gap-2'>
            <Button type='submit' size='sm' disabled={busy}>
              {t('check.saveVerdict')}
            </Button>
            <Button
              type='button'
              size='sm'
              variant='ghost'
              onClick={() => setDisagreeing(false)}
            >
              {t('common:actions.cancel')}
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}
