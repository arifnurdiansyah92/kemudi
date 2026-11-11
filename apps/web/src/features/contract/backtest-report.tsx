import { useFormat } from '@/i18n/format'
import { Check, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  isPrediction,
  scopeLabels,
  type Backtest,
  type BacktestResult,
} from '@/lib/kemudi-ai/queries'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScopeChip } from './scope-label'

const confusionColumns = [...scopeLabels, 'error'] as const

const pct = (
  v: number | null,
  f: (n: number, o?: Intl.NumberFormatOptions) => string
) => (v === null ? '—' : f(v, { style: 'percent', maximumFractionDigits: 0 }))

/** The scorecard of one backtest run, with the PM's review per request. */
export function BacktestReport({
  data,
  canReview,
  onVerdict,
}: {
  data: Backtest
  canReview: boolean
  onVerdict: (resultId: number, verdict: 'right' | 'wrong' | null) => void
}) {
  const { t } = useTranslation('contract')
  const format = useFormat()
  const m = data.metrics

  return (
    <div className='grid gap-8'>
      <dl className='grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2 lg:grid-cols-4'>
        <Metric
          label={t('backtest.metrics.accuracy')}
          value={pct(m.accuracy, format.number)}
          detail={t('backtest.metrics.accuracyDetail', {
            correct: m.correct,
            total: m.total,
          })}
        />
        <Metric
          label={t('backtest.metrics.crCaught')}
          value={pct(m.cr_recall, format.number)}
          detail={t('backtest.metrics.crCaughtDetail')}
        />
        <Metric
          label={t('backtest.metrics.falseCr')}
          value={pct(m.false_cr_rate, format.number)}
          detail={t('backtest.metrics.falseCrDetail')}
        />
        <Metric
          label={t('backtest.metrics.value')}
          value={format.rupiah(m.value_predicted_idr)}
          detail={t('backtest.metrics.valueDetail', {
            expected: format.rupiah(m.value_expected_idr),
          })}
        />
      </dl>
      <p className='-mt-5 text-sm text-muted-foreground'>
        {t('backtest.metrics.verdicts', m.verdicts)}
      </p>

      <section className='grid gap-2'>
        <h3 className='text-sm font-semibold'>
          {t('backtest.confusion.title')}
        </h3>
        <div className='overflow-x-auto'>
          <table className='text-sm'>
            <thead>
              <tr className='text-xs text-muted-foreground'>
                <th className='py-1.5 pe-4 text-start font-medium'>
                  {t('backtest.confusion.expected')}
                </th>
                {scopeLabels.map((l) => (
                  <th key={l} className='px-3 py-1.5 text-end font-medium'>
                    {t(`labels.${l}`)}
                  </th>
                ))}
                <th className='px-3 py-1.5 text-end font-medium'>
                  {t('backtest.confusion.error')}
                </th>
              </tr>
            </thead>
            <tbody>
              {scopeLabels.map((exp) => (
                <tr key={exp} className='border-t'>
                  <th className='py-1.5 pe-4 text-start font-normal'>
                    <ScopeChip label={exp} />
                  </th>
                  {confusionColumns.map((pred) => {
                    const n = m.confusion[exp]?.[pred] ?? 0
                    return (
                      <td
                        key={pred}
                        className={cn(
                          'px-3 py-1.5 text-end tabular-nums',
                          pred === exp
                            ? 'font-semibold'
                            : n
                              ? 'text-destructive'
                              : 'text-muted-foreground'
                        )}
                      >
                        {n}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className='overflow-x-auto'>
        <table className='w-full min-w-[56rem] text-sm'>
          <thead>
            <tr className='border-b text-xs text-muted-foreground'>
              <th className='py-2 pe-3 text-start font-medium'>
                {t('backtest.table.request')}
              </th>
              <th className='px-3 py-2 text-start font-medium'>
                {t('backtest.table.expected')}
              </th>
              <th className='px-3 py-2 text-start font-medium'>
                {t('backtest.table.suggested')}
              </th>
              <th className='px-3 py-2 text-end font-medium'>
                {t('backtest.table.price')}
              </th>
              <th className='py-2 ps-3 text-end font-medium'>
                {t('backtest.table.review')}
              </th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((r) => (
              <ResultRow
                key={r.id}
                r={r}
                canReview={canReview}
                onVerdict={onVerdict}
              />
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail: string
}) {
  return (
    <div className='bg-card p-4'>
      <dt className='text-xs font-medium text-muted-foreground'>{label}</dt>
      <dd className='mt-1 text-2xl font-semibold tracking-tight tabular-nums'>
        {value}
      </dd>
      <dd className='mt-0.5 text-xs text-muted-foreground'>{detail}</dd>
    </div>
  )
}

function ResultRow({
  r,
  canReview,
  onVerdict,
}: {
  r: BacktestResult
  canReview: boolean
  onVerdict: (resultId: number, verdict: 'right' | 'wrong' | null) => void
}) {
  const { t } = useTranslation('contract')
  const format = useFormat()
  const p = isPrediction(r.predicted) ? r.predicted : null
  const agrees = p?.label === r.expected.label
  const effort = p
    ? Object.entries(p.effort_days)
        .map(
          ([role, d]) =>
            `${role} ${t('backtest.table.days', { days: format.number(d) })}`
        )
        .join(', ')
    : ''

  return (
    <tr className='border-b align-top last:border-b-0'>
      <td className='max-w-md py-3 pe-3'>
        <p className='text-xs text-muted-foreground tabular-nums'>
          {r.ticket_id} · {r.date && format.date(r.date)} ·{' '}
          {r.source === 'real'
            ? t('backtest.table.real')
            : t('backtest.table.synthetic')}
        </p>
        <p className='mt-1 whitespace-pre-line'>{r.text}</p>
      </td>
      <td className='px-3 py-3'>
        <ScopeChip label={r.expected.label} />
        {r.expected.waived && (
          <p className='mt-1 text-xs text-muted-foreground'>
            {t('backtest.table.waived')}
          </p>
        )}
      </td>
      <td className='max-w-sm px-3 py-3'>
        {p ? (
          <>
            <ScopeChip
              label={p.label}
              className={cn(!agrees && 'border-destructive/50')}
            />
            <p className='mt-1.5 text-muted-foreground'>{p.reason}</p>
            {p.clause && (
              <p className='mt-1 text-xs text-muted-foreground'>{p.clause}</p>
            )}
            {p.question && (
              <p className='mt-1 text-xs'>
                {t('backtest.table.question', { question: p.question })}
              </p>
            )}
            {effort && (
              <p className='mt-1 text-xs text-muted-foreground'>{effort}</p>
            )}
          </>
        ) : (
          <p className='text-destructive'>
            {t('backtest.table.error', {
              error:
                r.predicted && 'error' in r.predicted ? r.predicted.error : '',
            })}
          </p>
        )}
      </td>
      <td className='px-3 py-3 text-end whitespace-nowrap tabular-nums'>
        {p && p.price_idr ? format.rupiah(p.price_idr) : '—'}
        {r.expected.price_idr ? (
          <p className='text-xs text-muted-foreground'>
            {format.rupiah(r.expected.price_idr)}
          </p>
        ) : null}
      </td>
      <td className='py-3 ps-3 text-end whitespace-nowrap'>
        <div className='inline-flex gap-1'>
          <Button
            variant={r.verdict === 'right' ? 'default' : 'outline'}
            size='icon'
            className='size-7'
            disabled={!canReview}
            aria-pressed={r.verdict === 'right'}
            aria-label={t('backtest.table.markRight')}
            onClick={() =>
              onVerdict(r.id, r.verdict === 'right' ? null : 'right')
            }
          >
            <Check />
          </Button>
          <Button
            variant={r.verdict === 'wrong' ? 'destructive' : 'outline'}
            size='icon'
            className='size-7'
            disabled={!canReview}
            aria-pressed={r.verdict === 'wrong'}
            aria-label={t('backtest.table.markWrong')}
            onClick={() =>
              onVerdict(r.id, r.verdict === 'wrong' ? null : 'wrong')
            }
          >
            <X />
          </Button>
        </div>
      </td>
    </tr>
  )
}
