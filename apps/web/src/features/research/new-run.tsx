import { useId, useState } from 'react'
import { toLanguage } from '@/i18n'
import { Info, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  PRODUCT_BRIEF_MAX,
  PRODUCT_BRIEF_MIN,
  PRODUCT_DEFAULT_PERIOD,
  productPeriods,
  useStartProductRun,
  type ProductAgents,
  type ProductKind,
  type ProductRun,
  type ProductRunOptions,
  type ProductRunSummary,
} from '@/lib/kemudi-ai/product'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { kindIcons } from './run-meta'

const selectClass =
  'h-9 w-full min-w-0 rounded-md border bg-background px-2 text-sm sm:w-auto sm:max-w-xs'

/** Pick an agent, brief it, start it. The run itself happens on the server. */
export function NewRun({
  slug,
  agents,
  runs,
  onStarted,
}: {
  slug: string
  agents: ProductAgents
  /** The project's runs: finished competitor runs can feed `features`. */
  runs: ProductRunSummary[]
  onStarted: (run: ProductRun) => void
}) {
  const { t, i18n } = useTranslation(['agent', 'common'])
  const id = useId()
  const start = useStartProductRun(slug)

  const [picked, setPicked] = useState<ProductKind | null>(null)
  const [brief, setBrief] = useState('')
  const [lang, setLang] = useState<'id' | 'en'>(
    () => toLanguage(i18n.language) ?? 'id'
  )
  const [days, setDays] = useState<number>(PRODUCT_DEFAULT_PERIOD)
  const [basedOn, setBasedOn] = useState<number | null>(null)

  const agent = agents.agents.find((a) => a.kind === picked) ?? agents.agents[0]
  if (!agent) return null
  const kind = agent.kind

  const competitorRuns = runs.filter(
    (r) => r.kind === 'competitor' && r.status === 'done'
  )
  // A run deleted since it was picked no longer counts.
  const based = competitorRuns.find((r) => r.id === basedOn)?.id
  const briefRequired = kind === 'custom'
  const tooShort = briefRequired && brief.trim().length < PRODUCT_BRIEF_MIN
  const pending = start.isPending

  const options: ProductRunOptions =
    kind === 'report'
      ? { days }
      : kind === 'features' && based != null
        ? { based_on: based }
        : {}

  return (
    <form
      className='grid gap-5'
      aria-labelledby={`${id}-title`}
      onSubmit={(e) => {
        e.preventDefault()
        if (tooShort || pending) return
        start.mutate(
          { kind, brief: brief.trim(), lang, options },
          {
            onSuccess: (run) => {
              setBrief('')
              onStarted(run)
            },
          }
        )
      }}
    >
      <h2 id={`${id}-title`} className='text-base font-semibold'>
        {t('research.new.title')}
      </h2>

      <fieldset className='grid gap-2' disabled={pending}>
        <legend className='mb-2 text-sm font-medium'>
          {t('research.new.agent')}
        </legend>
        <div className='grid gap-2 sm:grid-cols-2'>
          {agents.agents.map((a) => {
            const Icon = kindIcons[a.kind]
            return (
              <label
                key={a.kind}
                className='flex cursor-pointer gap-3 rounded-lg border bg-card p-3 transition-colors hover:bg-accent/50 has-checked:border-primary has-checked:bg-primary/5 has-focus-visible:ring-[3px] has-focus-visible:ring-ring/50 has-disabled:cursor-not-allowed has-disabled:opacity-60'
              >
                <input
                  type='radio'
                  name={`${id}-kind`}
                  className='sr-only'
                  checked={a.kind === kind}
                  aria-labelledby={`${id}-${a.kind}-label`}
                  aria-describedby={`${id}-${a.kind}-desc`}
                  onChange={() => setPicked(a.kind)}
                />
                <Icon
                  aria-hidden
                  className='mt-0.5 size-4 shrink-0 text-muted-foreground'
                />
                <span className='grid min-w-0 gap-0.5'>
                  <span
                    id={`${id}-${a.kind}-label`}
                    className='text-sm font-medium'
                  >
                    {t(`research.kinds.${a.kind}.label`)}
                  </span>
                  <span
                    id={`${id}-${a.kind}-desc`}
                    className='text-sm text-muted-foreground'
                  >
                    {t(`research.kinds.${a.kind}.description`)}
                  </span>
                </span>
              </label>
            )
          })}
        </div>
      </fieldset>

      {!agents.web && agent.needs_web && (
        <Alert>
          <Info />
          <AlertTitle>{t('research.new.noWeb.title')}</AlertTitle>
          <AlertDescription>{t('research.new.noWeb.body')}</AlertDescription>
        </Alert>
      )}

      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-brief`}>
          {briefRequired
            ? t('research.new.brief')
            : t('research.new.briefOptional')}
        </Label>
        <Textarea
          id={`${id}-brief`}
          value={brief}
          rows={5}
          maxLength={PRODUCT_BRIEF_MAX}
          required={briefRequired}
          placeholder={t(`research.kinds.${kind}.placeholder`)}
          aria-describedby={briefRequired ? `${id}-brief-hint` : undefined}
          className='field-sizing-content max-h-[50vh] min-h-28'
          disabled={pending}
          onChange={(e) => setBrief(e.target.value)}
        />
        {briefRequired && (
          <p id={`${id}-brief-hint`} className='text-xs text-muted-foreground'>
            {t('research.new.briefShort', { count: PRODUCT_BRIEF_MIN })}
          </p>
        )}
      </div>

      <div className='flex flex-wrap items-start gap-x-4 gap-y-4'>
        {kind === 'report' && (
          <div className='grid w-full gap-1.5 sm:w-auto'>
            <Label htmlFor={`${id}-days`}>{t('research.new.period')}</Label>
            <select
              id={`${id}-days`}
              value={days}
              disabled={pending}
              onChange={(e) => setDays(Number(e.target.value))}
              className={selectClass}
            >
              {productPeriods.map((d) => (
                <option key={d} value={d}>
                  {t('research.new.periodDays', { count: d })}
                </option>
              ))}
            </select>
          </div>
        )}
        {kind === 'features' && (
          <div className='grid w-full gap-1.5 sm:w-auto'>
            <Label htmlFor={`${id}-based`}>{t('research.new.basedOn')}</Label>
            <select
              id={`${id}-based`}
              value={based ?? ''}
              disabled={pending}
              aria-describedby={`${id}-based-hint`}
              onChange={(e) =>
                setBasedOn(e.target.value ? Number(e.target.value) : null)
              }
              className={selectClass}
            >
              <option value=''>{t('research.new.basedOnNone')}</option>
              {competitorRuns.map((r) => (
                <option key={r.id} value={r.id}>
                  #{r.id} {r.title || t('research.kinds.competitor.label')}
                </option>
              ))}
            </select>
            <p
              id={`${id}-based-hint`}
              className='max-w-xs text-xs text-muted-foreground'
            >
              {t('research.new.basedOnHint')}
            </p>
          </div>
        )}
        <div className='grid w-full gap-1.5 sm:w-auto'>
          <Label htmlFor={`${id}-lang`}>{t('research.new.language')}</Label>
          <select
            id={`${id}-lang`}
            value={lang}
            disabled={pending}
            onChange={(e) => setLang(e.target.value as 'id' | 'en')}
            className={selectClass}
          >
            <option value='id'>{t('common:language.id')}</option>
            <option value='en'>{t('common:language.en')}</option>
          </select>
        </div>
      </div>

      <div className='flex flex-wrap items-center gap-x-4 gap-y-2'>
        <Button type='submit' disabled={pending || tooShort}>
          {pending && <Loader2 className='animate-spin' />}
          {t('research.new.start')}
        </Button>
        <p className='min-w-0 text-sm text-muted-foreground'>
          {t('research.new.duration')}
        </p>
      </div>
    </form>
  )
}
