import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Loader2, Plus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useSaveRateCard,
  useUploadContract,
  type ContractState,
  type RateCard,
} from '@/lib/kemudi-ai/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const defaultRates: RateCard = {
  currency: 'IDR',
  per_day: {
    pm: 1_500_000,
    backend: 1_500_000,
    frontend: 1_250_000,
    qa: 1_000_000,
  },
}

export function ContractUpload({
  slug,
  state,
  isAdmin,
}: {
  slug: string
  state: ContractState
  isAdmin: boolean
}) {
  const { t } = useTranslation(['contract', 'common'])
  const upload = useUploadContract(slug)
  const contract = state.contract
  const [file, setFile] = useState<File | null>(null)
  const [lang, setLang] = useState<'id' | 'en'>(contract?.lang ?? 'id')

  return (
    <div className='grid gap-10'>
      <section className='grid gap-4'>
        <div>
          <h2 className='text-base font-semibold'>{t('upload.title')}</h2>
          <p className='mt-1 text-sm text-muted-foreground'>
            {t('upload.description')}
          </p>
        </div>
        {contract ? (
          <p className='text-sm'>
            {t('upload.current', {
              file: contract.filename,
              count: contract.sections.length,
            })}
          </p>
        ) : (
          <p className='text-sm text-muted-foreground'>{t('upload.empty')}</p>
        )}
        {isAdmin ? (
          <form
            className='grid gap-4 sm:grid-cols-[1fr_auto_auto] sm:items-end'
            onSubmit={(e) => {
              e.preventDefault()
              if (!file) return
              upload.mutate(
                {
                  file,
                  lang,
                  rateCard: contract?.rate_card?.per_day
                    ? contract.rate_card
                    : defaultRates,
                },
                { onSuccess: () => setFile(null) }
              )
            }}
          >
            <div className='grid gap-1.5'>
              <Label htmlFor='contract-file'>{t('upload.file')}</Label>
              <Input
                id='contract-file'
                type='file'
                accept='.pdf,.docx'
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className='grid gap-1.5'>
              <Label htmlFor='contract-lang'>{t('upload.language')}</Label>
              <select
                id='contract-lang'
                value={lang}
                onChange={(e) => setLang(e.target.value as 'id' | 'en')}
                className='h-9 rounded-md border bg-background px-2 text-sm'
                title={t('upload.languageHint')}
              >
                <option value='id'>{t('common:language.id')}</option>
                <option value='en'>{t('common:language.en')}</option>
              </select>
            </div>
            <Button type='submit' disabled={!file || upload.isPending}>
              {upload.isPending && <Loader2 className='animate-spin' />}
              {contract ? t('upload.replace') : t('upload.submit')}
            </Button>
          </form>
        ) : (
          <p className='text-sm text-muted-foreground'>{t('adminOnly')}</p>
        )}
        {contract && (
          <details className='rounded-lg border bg-card'>
            <summary className='cursor-pointer px-4 py-2.5 text-sm font-medium'>
              {t('upload.sections')} ({contract.sections.length})
            </summary>
            {contract.sections.length === 0 ? (
              <p className='px-4 pb-3 text-sm text-muted-foreground'>
                {t('upload.noSections')}
              </p>
            ) : (
              <ol className='divide-y border-t'>
                {contract.sections.map((s) => (
                  <li key={s.ref} className='px-4 py-3 text-sm'>
                    <p className='font-medium'>
                      <span className='me-2 text-muted-foreground tabular-nums'>
                        {s.ref}
                      </span>
                      {s.title}
                    </p>
                    <p className='mt-1 line-clamp-4 whitespace-pre-line text-muted-foreground'>
                      {s.text}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </details>
        )}
      </section>
      {contract && (
        <RateCardEditor
          slug={slug}
          initial={
            contract.rate_card?.per_day ? contract.rate_card : defaultRates
          }
          isAdmin={isAdmin}
        />
      )}
    </div>
  )
}

function RateCardEditor({
  slug,
  initial,
  isAdmin,
}: {
  slug: string
  initial: RateCard
  isAdmin: boolean
}) {
  const { t } = useTranslation('contract')
  const format = useFormat()
  const save = useSaveRateCard(slug)
  const [rows, setRows] = useState(() => Object.entries(initial.per_day))

  return (
    <section className='grid gap-4'>
      <div>
        <h2 className='text-base font-semibold'>{t('rateCard.title')}</h2>
        <p className='mt-1 text-sm text-muted-foreground'>
          {t('rateCard.description')}
        </p>
      </div>
      <table className='w-full max-w-xl text-sm'>
        <thead>
          <tr className='border-b text-start text-xs text-muted-foreground'>
            <th className='py-2 text-start font-medium'>
              {t('rateCard.role')}
            </th>
            <th className='py-2 text-end font-medium'>{t('rateCard.rate')}</th>
            <th className='w-8' />
          </tr>
        </thead>
        <tbody>
          {rows.map(([role, rate], i) => (
            <tr key={i} className='border-b last:border-b-0'>
              <td className='py-1.5 pe-3'>
                {isAdmin ? (
                  <Input
                    aria-label={t('rateCard.role')}
                    value={role}
                    placeholder={t('rateCard.rolePlaceholder')}
                    onChange={(e) =>
                      setRows(
                        rows.map((r, j) =>
                          j === i ? [e.target.value, r[1]] : r
                        )
                      )
                    }
                    className='h-8'
                  />
                ) : (
                  role
                )}
              </td>
              <td className='py-1.5 text-end tabular-nums'>
                {isAdmin ? (
                  <Input
                    aria-label={t('rateCard.rate')}
                    type='number'
                    min={0}
                    step={50_000}
                    value={rate}
                    onChange={(e) =>
                      setRows(
                        rows.map((r, j) =>
                          j === i ? [r[0], Number(e.target.value)] : r
                        )
                      )
                    }
                    className='h-8 text-end'
                  />
                ) : (
                  format.rupiah(rate)
                )}
              </td>
              <td className='ps-1'>
                {isAdmin && (
                  <Button
                    variant='ghost'
                    size='icon'
                    className='size-7'
                    aria-label={t('rateCard.removeRole', { role })}
                    onClick={() => setRows(rows.filter((_, j) => j !== i))}
                  >
                    <X />
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {isAdmin && (
        <div className='flex flex-wrap gap-2'>
          <Button
            variant='outline'
            size='sm'
            onClick={() => setRows([...rows, ['', 0]])}
          >
            <Plus />
            {t('rateCard.addRole')}
          </Button>
          <Button
            size='sm'
            disabled={save.isPending || rows.some(([r]) => !r.trim())}
            onClick={() =>
              save.mutate({
                currency: 'IDR',
                per_day: Object.fromEntries(
                  rows.map(([r, v]) => [r.trim(), v])
                ),
              })
            }
          >
            {save.isPending && <Loader2 className='animate-spin' />}
            {t('rateCard.save')}
          </Button>
        </div>
      )}
    </section>
  )
}
