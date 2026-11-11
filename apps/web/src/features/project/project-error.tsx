import { AxiosError } from 'axios'
import { Link, type ErrorComponentProps } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

export function ProjectError({ error, reset }: ErrorComponentProps) {
  const { t } = useTranslation(['shell', 'common'])
  const status =
    error instanceof AxiosError ? error.response?.status : undefined
  const missing = status === 404 || status === 403

  return (
    <div className='flex min-h-[60svh] flex-col items-center justify-center gap-2 px-4 text-center'>
      <h1 className='text-xl font-semibold'>
        {missing ? t('projectError.notFound') : t('projectError.loadFailed')}
      </h1>
      <p className='max-w-sm text-sm text-muted-foreground'>
        {missing
          ? t('projectError.notFoundHelp')
          : t('projectError.loadFailedHelp')}
      </p>
      <div className='mt-4 flex gap-2'>
        {!missing && (
          <Button onClick={reset}>{t('common:actions.retry')}</Button>
        )}
        <Button variant='outline' asChild>
          <Link to='/projects'>{t('projectSwitcher.all')}</Link>
        </Button>
      </div>
    </div>
  )
}
