import { useNavigate, useRouter } from '@tanstack/react-router'
import { Trans, useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'

type GeneralErrorProps = React.HTMLAttributes<HTMLDivElement> & {
  minimal?: boolean
}

export function GeneralError({
  className,
  minimal = false,
}: GeneralErrorProps) {
  const { t } = useTranslation('shell')
  const navigate = useNavigate()
  const { history } = useRouter()
  return (
    <div className={cn('h-svh w-full', className)}>
      <div className='m-auto flex h-full w-full flex-col items-center justify-center gap-2'>
        {!minimal && (
          <h1 className='text-[7rem] leading-tight font-bold'>500</h1>
        )}
        <span className='font-medium'>{t('errorPage.general.title')}</span>
        <p className='text-center text-muted-foreground'>
          <Trans t={t} i18nKey='errorPage.general.description' />
        </p>
        {!minimal && (
          <div className='mt-6 flex gap-4'>
            <Button variant='outline' onClick={() => history.go(-1)}>
              {t('errorPage.goBack')}
            </Button>
            <Button onClick={() => navigate({ to: '/' })}>
              {t('errorPage.home')}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
