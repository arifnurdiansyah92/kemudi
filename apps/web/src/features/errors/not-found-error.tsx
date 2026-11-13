import { Link, useNavigate, useRouter } from '@tanstack/react-router'
import { Trans, useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

export function NotFoundError() {
  const { t } = useTranslation('shell')
  const navigate = useNavigate()
  const { history } = useRouter()
  return (
    <div className='h-svh'>
      <div className='m-auto flex h-full w-full flex-col items-center justify-center gap-2'>
        <h1 className='text-[7rem] leading-tight font-bold'>404</h1>
        <span className='font-medium'>{t('errorPage.notFound.title')}</span>
        <p className='text-center text-muted-foreground'>
          <Trans t={t} i18nKey='errorPage.notFound.description' />
        </p>
        <div className='mt-6 flex gap-4'>
          <Button variant='outline' onClick={() => history.go(-1)}>
            {t('errorPage.goBack')}
          </Button>
          <Button variant='outline' onClick={() => navigate({ to: '/' })}>
            {t('errorPage.home')}
          </Button>
          <Button asChild>
            <Link to='/projects'>{t('errorPage.backToProjects')}</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}
