import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Download, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  downloadChecksCsv,
  useProjectChecks,
  type CrCheck,
} from '@/lib/kemudi-ai/queries'
import { onFail } from '@/lib/taiga/items'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ScopeChip } from './scope-label'

/** Every CR check in the project with the PM's verdict, and a CSV export. */
export function ChecksTab({ slug }: { slug: string }) {
  const { t } = useTranslation('contract')
  const checks = useProjectChecks(slug)
  const [exporting, setExporting] = useState(false)

  const exportCsv = async () => {
    setExporting(true)
    try {
      await downloadChecksCsv(slug)
    } catch (e) {
      onFail(e)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className='grid gap-6'>
      <div className='flex flex-wrap items-start justify-between gap-4'>
        <p className='max-w-2xl text-sm text-muted-foreground'>
          {t('checks.description')}
        </p>
        <Button
          variant='outline'
          size='sm'
          disabled={exporting || !checks.data?.checks.length}
          onClick={exportCsv}
        >
          {exporting ? <Loader2 className='animate-spin' /> : <Download />}
          {t('checks.export')}
        </Button>
      </div>
      {checks.isPending ? (
        <Skeleton className='h-40' />
      ) : checks.isError ? (
        <p role='alert' className='text-sm text-destructive'>
          {t('unavailable')}
        </p>
      ) : checks.data.checks.length === 0 ? (
        <p className='text-sm text-muted-foreground'>{t('checks.empty')}</p>
      ) : (
        <ChecksTable checks={checks.data.checks} />
      )}
    </div>
  )
}

export function ChecksTable({ checks }: { checks: CrCheck[] }) {
  const { t } = useTranslation(['contract', 'common'])
  const format = useFormat()
  const showPrice = checks.some((c) => c.price_idr !== null)

  return (
    <div className='overflow-x-auto'>
      <table className='w-full min-w-[48rem] text-sm'>
        <thead>
          <tr className='border-b text-xs text-muted-foreground'>
            <th className='py-2 pe-3 text-start font-medium'>
              {t('checks.ticket')}
            </th>
            <th className='px-3 py-2 text-start font-medium'>
              {t('checks.suggested')}
            </th>
            <th className='px-3 py-2 text-end font-medium'>
              {t('checks.effort')}
            </th>
            {showPrice && (
              <th className='px-3 py-2 text-end font-medium'>
                {t('checks.price')}
              </th>
            )}
            <th className='px-3 py-2 text-start font-medium'>
              {t('checks.verdict')}
            </th>
            <th className='py-2 ps-3 text-end font-medium'>
              {t('checks.checked')}
            </th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.id} className='border-b align-top last:border-b-0'>
              <td className='max-w-xs py-3 pe-3'>
                <p className='text-xs text-muted-foreground tabular-nums'>
                  {t(
                    c.ticket_kind === 'issue'
                      ? 'common:terms.issue'
                      : 'common:terms.story',
                    { count: 1 }
                  )}{' '}
                  #{c.ticket_ref}
                </p>
                <p className='mt-0.5'>{c.subject}</p>
              </td>
              <td className='max-w-sm px-3 py-3'>
                <ScopeChip label={c.label} />
                <p className='mt-1.5 text-muted-foreground'>{c.reasoning}</p>
                {c.clause && (
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {c.clause}
                  </p>
                )}
              </td>
              <td className='px-3 py-3 text-end whitespace-nowrap tabular-nums'>
                {c.effort_total_days
                  ? t('check.days', {
                      days: format.number(c.effort_total_days),
                    })
                  : '—'}
              </td>
              {showPrice && (
                <td className='px-3 py-3 text-end whitespace-nowrap tabular-nums'>
                  {c.price_idr ? format.rupiah(c.price_idr) : '—'}
                </td>
              )}
              <td className='px-3 py-3'>
                <p>{t(`checks.verdicts.${c.verdict ?? 'pending'}`)}</p>
                {c.corrected_label && (
                  <p className='mt-1 text-xs'>
                    {t('check.correctedTo', {
                      label: t(`labels.${c.corrected_label}`),
                    })}
                  </p>
                )}
                {c.decided_by && (
                  <p className='mt-1 text-xs text-muted-foreground'>
                    {c.decided_by}
                  </p>
                )}
              </td>
              <td className='py-3 ps-3 text-end text-xs whitespace-nowrap text-muted-foreground'>
                {format.date(c.checked_at, 'dateTime')}
                <p>{c.checked_by}</p>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
