import { Link, useParams } from '@tanstack/react-router'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'

export function NoSprint() {
  const { slug } = useParams({ from: '/_authenticated/p/$slug' })
  return (
    <>
      <AppHeader crumbs={[{ label: 'Taskboard' }]} />
      <Main>
        <h1 className='text-2xl font-semibold tracking-tight'>Taskboard</h1>
        <p className='mt-2 text-sm text-muted-foreground'>
          There is no open sprint.{' '}
          <Link
            to='/p/$slug/backlog'
            params={{ slug }}
            className='text-foreground underline underline-offset-4'
          >
            Create one in the backlog
          </Link>
          .
        </p>
      </Main>
    </>
  )
}
