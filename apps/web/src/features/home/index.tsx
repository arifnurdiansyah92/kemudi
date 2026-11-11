import { Link } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/stores/auth-store'
import { useMyItems, type MyItem } from '@/lib/taiga/me'
import { useProjects } from '@/lib/taiga/queries'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { StatusDot } from '@/features/story/parts'

const PAGE: Record<MyItem['kind'], string> = {
  userstory: '/p/$slug/backlog',
  task: '/p/$slug/backlog',
  issue: '/p/$slug/issues',
  epic: '/p/$slug/epics',
}

const KIND_LABEL = {
  userstory: 'common:terms.story_one',
  task: 'common:terms.task_one',
  issue: 'common:terms.issue_one',
  epic: 'common:terms.epic_one',
} as const satisfies Record<MyItem['kind'], string>

export function Home() {
  const { t } = useTranslation(['home', 'common'])
  const user = useAuthStore((s) => s.session?.user)
  const working = useMyItems('assigned')
  const watching = useMyItems('watching')
  const projects = useProjects()

  return (
    <>
      <AppHeader crumbs={[{ label: t('home.title') }]} />
      <Main width='list'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {user
            ? t('home.greeting', { name: user.full_name_display })
            : t('home.title')}
        </h1>
        <div className='mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]'>
          <div className='grid gap-8'>
            <ItemList
              title={t('home.workingOn')}
              empty={t('home.workingOnEmpty')}
              query={working}
            />
            <ItemList
              title={t('home.watching')}
              empty={t('home.watchingEmpty')}
              query={watching}
            />
          </div>
          <section aria-labelledby='home-projects'>
            <div className='mb-2 flex items-baseline justify-between'>
              <h2 id='home-projects' className='font-semibold'>
                {t('common:terms.project_other')}
              </h2>
              <Link
                to='/projects'
                className='text-sm text-muted-foreground hover:text-foreground'
              >
                {t('home.allProjects')}
              </Link>
            </div>
            {projects.isPending ? (
              <Skeleton className='h-24 w-full' />
            ) : (
              <ul className='grid gap-1'>
                {(projects.data ?? []).slice(0, 8).map((p) => (
                  <li key={p.id}>
                    <Link
                      to='/p/$slug'
                      params={{ slug: p.slug }}
                      className='flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm hover:bg-accent'
                    >
                      <span
                        aria-hidden='true'
                        className='flex size-6 items-center justify-center rounded bg-primary text-xs font-semibold text-primary-foreground'
                      >
                        {p.name.slice(0, 1).toUpperCase()}
                      </span>
                      <span className='truncate'>{p.name}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </Main>
    </>
  )
}

function ItemList({
  title,
  empty,
  query,
}: {
  title: string
  empty: string
  query: ReturnType<typeof useMyItems>
}) {
  const { t } = useTranslation(['home', 'common'])
  const format = useFormat()
  const items = query.data ?? []
  return (
    <section>
      <h2 className='mb-2 font-semibold'>
        {title}
        {items.length > 0 && (
          <span className='ms-2 text-sm font-normal text-muted-foreground tabular-nums'>
            {items.length}
          </span>
        )}
      </h2>
      {query.isPending ? (
        <Skeleton className='h-24 w-full' />
      ) : items.length === 0 ? (
        <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
          {empty}
        </p>
      ) : (
        <ul className='divide-y rounded-lg border bg-card'>
          {items.map((item) => (
            <li key={`${item.kind}-${item.id}`}>
              <Link
                to={PAGE[item.kind]}
                params={{ slug: item.project_extra_info.slug }}
                search={{ ref: item.ref }}
                className='flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-accent/50'
              >
                <span
                  className={cn(
                    'w-12 shrink-0 text-xs text-muted-foreground',
                    item.kind === 'issue' && 'text-destructive'
                  )}
                >
                  {t(KIND_LABEL[item.kind])}
                </span>
                <span className='min-w-0 flex-1 truncate'>
                  <span className='me-1.5 text-xs text-muted-foreground tabular-nums'>
                    #{item.ref}
                  </span>
                  {item.subject}
                </span>
                <span className='hidden items-center gap-1.5 text-xs text-muted-foreground sm:inline-flex'>
                  <StatusDot color={item.status_extra_info.color} />
                  {item.status_extra_info.name}
                </span>
                <span className='hidden w-44 truncate text-end text-xs text-muted-foreground md:block lg:w-56'>
                  {t('home.itemMeta', {
                    project: item.project_extra_info.name,
                    time: format.timeAgo(item.modified_date),
                  })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
