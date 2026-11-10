import { Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useProjects } from '@/lib/taiga/queries'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { ProjectList } from './project-list'

export function Projects() {
  const { data: projects, isPending, isError, refetch } = useProjects()

  return (
    <>
      <AppHeader crumbs={[{ label: 'Projects' }]} />
      <Main className='max-w-4xl'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-tight'>Projects</h1>
            <p className='mt-1 text-sm text-muted-foreground'>
              Every project you are a member of; drag to put them in your order.{' '}
              <Link
                to='/discover'
                className='text-foreground underline-offset-4 hover:underline'
              >
                Discover public projects
              </Link>
            </p>
          </div>
          <Button size='sm' asChild>
            <Link to='/projects/new'>
              <Plus />
              New project
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
              Projects could not be loaded.{' '}
              <button
                className='underline underline-offset-4'
                onClick={() => refetch()}
              >
                Try again
              </button>
            </p>
          ) : projects.length === 0 ? (
            <div className='rounded-lg border border-dashed p-10 text-center'>
              <p className='font-medium'>No projects yet</p>
              <p className='mt-1 text-sm text-muted-foreground'>
                Create one, or ask a project admin to invite you.
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
