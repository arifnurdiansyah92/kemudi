import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useProjects } from '@/lib/taiga/queries'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { ProjectList } from './project-list'

export function Projects() {
  const { t } = useTranslation(['home', 'common'])
  const { data: projects, isPending, isError, refetch } = useProjects()

  return (
    <>
      <AppHeader crumbs={[{ label: t('common:terms.project_other') }]} />
      <Main width='reading'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-tight'>
              {t('common:terms.project_other')}
            </h1>
            <p className='mt-1 text-sm text-muted-foreground'>
              {t('projects.intro')}
            </p>
          </div>
          <Button size='sm' asChild>
            <Link to='/projects/new'>
              <Plus />
              {t('projects.newProject')}
            </Link>
          </Button>
        </div>

        <div className='mt-8'>
          {isPending ? (
            <div className='space-y-2'>
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className='h-20 w-full' />
              ))}
            </div>
          ) : isError ? (
            <p className='text-sm'>
              {t('projects.loadFailed')}{' '}
              <button
                className='underline underline-offset-4'
                onClick={() => refetch()}
              >
                {t('common:actions.retry')}
              </button>
            </p>
          ) : projects.length === 0 ? (
            <div className='rounded-lg border border-dashed p-10 text-center'>
              <p className='font-medium'>{t('projects.emptyTitle')}</p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('projects.emptyHint')}
              </p>
            </div>
          ) : (
            <ProjectList projects={projects} />
          )}
        </div>
      </Main>
    </>
  )
}
