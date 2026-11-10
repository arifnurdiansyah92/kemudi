import { Link } from '@tanstack/react-router'
import { Lock } from 'lucide-react'
import { useProjects } from '@/lib/taiga/queries'
import { timeAgo } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'

export function Projects() {
  const { data: projects, isPending, isError, refetch } = useProjects()

  return (
    <>
      <AppHeader crumbs={[{ label: 'Projects' }]} />
      <Main className='max-w-4xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>Projects</h1>
        <p className='mt-1 text-sm text-muted-foreground'>
          Every project you are a member of.
        </p>

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
                Ask a project admin to invite you.
              </p>
            </div>
          ) : (
            <ul className='divide-y rounded-lg border bg-card'>
              {projects.map((project) => (
                <li key={project.id}>
                  <Link
                    to='/p/$slug'
                    params={{ slug: project.slug }}
                    className='group flex items-start gap-4 px-5 py-4 transition-colors outline-none hover:bg-accent/60 focus-visible:bg-accent'
                  >
                    <span
                      aria-hidden='true'
                      className='mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-sm font-semibold text-primary-foreground'
                    >
                      {project.name.slice(0, 1).toUpperCase()}
                    </span>
                    <span className='min-w-0 flex-1'>
                      <span className='flex items-center gap-1.5 font-medium group-hover:underline group-hover:underline-offset-4'>
                        {project.name}
                        {project.is_private && (
                          <Lock
                            className='size-3.5 text-muted-foreground'
                            aria-label='Private'
                          />
                        )}
                      </span>
                      {project.description && (
                        <span className='mt-0.5 line-clamp-1 block text-sm text-muted-foreground'>
                          {project.description}
                        </span>
                      )}
                    </span>
                    <span className='shrink-0 pt-0.5 text-xs text-muted-foreground tabular-nums max-sm:hidden'>
                      Updated {timeAgo(project.modified_date)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Main>
    </>
  )
}
