import { Trans, useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

export function MaintenanceError() {
  const { t } = useTranslation('shell')
  return (
    <div className='h-svh'>
      <div className='m-auto flex h-full w-full flex-col items-center justify-center gap-2'>
        <h1 className='text-[7rem] leading-tight font-bold'>503</h1>
        <span className='font-medium'>{t('errorPage.maintenance.title')}</span>
        <p className='text-center text-muted-foreground'>
          <Trans t={t} i18nKey='errorPage.maintenance.description' />
        </p>
        <div className='mt-6 flex gap-4'>
          <Button variant='outline'>
            {t('errorPage.maintenance.learnMore')}
          </Button>
        </div>
      </div>
    </div>
  )
}
