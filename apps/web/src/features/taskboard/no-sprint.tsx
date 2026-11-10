import { Link, useParams } from '@tanstack/react-router'
import { Trans, useTranslation } from 'react-i18next'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'

export function NoSprint() {
  const { t } = useTranslation(['backlog', 'common'])
  const { slug } = useParams({ from: '/_authenticated/p/$slug' })
  return (
    <>
      <AppHeader crumbs={[{ label: t('common:terms.taskboard') }]} />
      <Main>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('common:terms.taskboard')}
        </h1>
        <p className='mt-2 text-sm text-muted-foreground'>
          <Trans
            t={t}
            i18nKey='taskboard.noSprint'
            components={{
              link: (
                <Link
                  to='/p/$slug/backlog'
                  params={{ slug }}
                  className='text-foreground underline underline-offset-4'
                />
              ),
            }}
          />
        </p>
      </Main>
    </>
  )
}
