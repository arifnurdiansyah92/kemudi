import { useTranslation } from 'react-i18next'
import { useSetShowPrices } from '@/lib/kemudi-ai/queries'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

/** Per-project switch for Rupiah amounts in CR checks (off by default). */
export function PriceSetting({
  slug,
  showPrices,
  isAdmin,
}: {
  slug: string
  showPrices: boolean
  isAdmin: boolean
}) {
  const { t } = useTranslation('contract')
  const set = useSetShowPrices(slug)
  const checked = set.isPending ? (set.variables ?? showPrices) : showPrices

  return (
    <section className='grid gap-4'>
      <div>
        <h2 className='text-base font-semibold'>{t('prices.title')}</h2>
        <p className='mt-1 max-w-2xl text-sm text-muted-foreground'>
          {t('prices.description')}
        </p>
      </div>
      <div className='flex items-start gap-3'>
        <Switch
          id='show-prices'
          checked={checked}
          disabled={!isAdmin || set.isPending}
          onCheckedChange={(v) => set.mutate(v)}
        />
        <div className='grid gap-1'>
          <Label htmlFor='show-prices'>{t('prices.label')}</Label>
          <p className='text-xs text-muted-foreground'>
            {isAdmin ? t('prices.hint') : t('adminOnly')}
          </p>
        </div>
      </div>
    </section>
  )
}
