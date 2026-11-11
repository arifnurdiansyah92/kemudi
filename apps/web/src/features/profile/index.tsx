import { AxiosError } from 'axios'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/stores/auth-store'
import { api } from '@/lib/taiga/client'
import type { Id } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { UserAvatar } from '@/components/user-avatar'
import { StatusDot } from '@/features/story/parts'
import { Timeline } from '@/features/timeline/timeline'

interface PublicUser {
  id: Id
  username: string
  full_name_display: string
  bio: string
  photo: string | null
  big_photo: string | null
  color: string
  roles: string[]
}

interface Stats {
  total_num_projects: number
  total_num_contacts: number
  total_num_closed_userstories: number
  roles: string[]
}

/** An item or project from the watched, liked and voted lists. */
interface Listed {
  id: Id
  type: 'project' | 'userstory' | 'task' | 'issue' | 'epic'
  ref: number | null
  subject: string | null
  name: string | null
  slug: string | null
  project_name: string | null
  project_slug: string | null
  status: string | null
  status_color: string | null
}

const PAGE: Record<string, string> = {
  userstory: '/p/$slug/backlog',
  task: '/p/$slug/backlog',
  issue: '/p/$slug/issues',
  epic: '/p/$slug/epics',
}

const LISTS = ['watched', 'liked', 'voted'] as const

const KIND_LABEL: Record<
  string,
  `common:terms.${'story' | 'task' | 'issue' | 'epic'}_one`
> = {
  userstory: 'common:terms.story_one',
  task: 'common:terms.task_one',
  issue: 'common:terms.issue_one',
  epic: 'common:terms.epic_one',
}

export function Profile({ username }: { username: string }) {
  const { t } = useTranslation(['home', 'common'])
  const format = useFormat()
  const me = useAuthStore((s) => s.session?.user.username)
  const user = useQuery({
    queryKey: ['profile', username],
    queryFn: async () =>
      (
        await api.get<PublicUser>('/users/by_username', {
          params: { username },
        })
      ).data,
  })
  const stats = useQuery({
    queryKey: ['profile-stats', user.data?.id],
    enabled: !!user.data,
    queryFn: async () =>
      (await api.get<Stats>(`/users/${user.data!.id}/stats`)).data,
  })

  if (user.isError) {
    const missing =
      user.error instanceof AxiosError && user.error.response?.status === 404
    return (
      <>
        <AppHeader
          crumbs={[{ label: t('profile.people') }, { label: username }]}
        />
        <Main width='reading'>
          <p className='text-sm'>
            {missing
              ? t('profile.notFound', { username })
              : t('profile.loadFailed')}
          </p>
        </Main>
      </>
    )
  }

  const u = user.data
  return (
    <>
      <AppHeader
        crumbs={[
          { label: t('profile.people') },
          { label: u?.full_name_display ?? username },
        ]}
      />
      <Main width='reading'>
        {!u ? (
          <Skeleton className='h-24 w-full' />
        ) : (
          <header className='flex flex-wrap items-center gap-5'>
            <UserAvatar
              user={{ ...u, photo: u.big_photo ?? u.photo }}
              className='size-20 text-xl'
            />
            <div className='min-w-0 flex-1'>
              <h1 className='text-2xl font-semibold tracking-tight'>
                {u.full_name_display}
              </h1>
              <p className='text-sm text-muted-foreground'>
                @{u.username}
                {u.roles.length > 0 && `, ${u.roles.join(', ')}`}
              </p>
              {u.bio && <p className='mt-2 max-w-prose text-sm'>{u.bio}</p>}
            </div>
            {me === u.username && (
              <Button variant='outline' size='sm' asChild>
                <Link to='/settings/profile'>{t('profile.edit')}</Link>
              </Button>
            )}
          </header>
        )}
        {stats.data && (
          <dl className='mt-6 flex flex-wrap gap-x-8 gap-y-2 text-sm'>
            {[
              [t('common:terms.project_other'), stats.data.total_num_projects],
              [
                t('profile.stats.storiesClosed'),
                stats.data.total_num_closed_userstories,
              ],
              [t('profile.stats.contacts'), stats.data.total_num_contacts],
            ].map(([label, n]) => (
              <div key={label as string}>
                <dt className='text-xs text-muted-foreground'>{label}</dt>
                <dd className='text-lg font-semibold tabular-nums'>
                  {format.number(n as number)}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {u && (
          <Tabs defaultValue='activity' className='mt-8'>
            <TabsList className='flex-wrap'>
              <TabsTrigger value='activity'>
                {t('profile.tabs.activity')}
              </TabsTrigger>
              <TabsTrigger value='watched'>
                {t('profile.tabs.watching')}
              </TabsTrigger>
              <TabsTrigger value='liked'>{t('profile.tabs.liked')}</TabsTrigger>
              <TabsTrigger value='voted'>{t('profile.tabs.votes')}</TabsTrigger>
              <TabsTrigger value='contacts'>
                {t('profile.tabs.contacts')}
              </TabsTrigger>
            </TabsList>
            <TabsContent value='activity' className='mt-6'>
              <Timeline source={`user/${u.id}`} showProject />
            </TabsContent>
            {LISTS.map((list) => (
              <TabsContent key={list} value={list} className='mt-6'>
                <ListedItems userId={u.id} list={list} />
              </TabsContent>
            ))}
            <TabsContent value='contacts' className='mt-6'>
              <Contacts userId={u.id} />
            </TabsContent>
          </Tabs>
        )}
      </Main>
    </>
  )
}

function ListedItems({
  userId,
  list,
}: {
  userId: Id
  list: 'watched' | 'liked' | 'voted'
}) {
  const { t } = useTranslation(['home', 'common'])
  const items = useQuery({
    queryKey: ['profile-list', userId, list],
    queryFn: async () =>
      (await api.get<Listed[]>(`/users/${userId}/${list}`)).data,
  })
  if (items.isPending) return <Skeleton className='h-24 w-full' />
  if (!items.data?.length)
    return <p className='text-sm text-muted-foreground'>{t('profile.empty')}</p>
  return (
    <ul className='divide-y rounded-lg border bg-card'>
      {items.data.map((x) => (
        <li key={`${x.type}-${x.id}`}>
          {x.type === 'project' ? (
            <Link
              to='/p/$slug'
              params={{ slug: x.slug! }}
              className='flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-accent/50'
            >
              <span className='w-14 text-xs text-muted-foreground'>
                {t('common:terms.project_one')}
              </span>
              <span className='font-medium'>{x.name}</span>
            </Link>
          ) : (
            <Link
              to={PAGE[x.type]}
              params={{ slug: x.project_slug! }}
              search={{ ref: x.ref ?? undefined }}
              className='flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-accent/50'
            >
              <span className='w-14 text-xs text-muted-foreground capitalize'>
                {KIND_LABEL[x.type] ? t(KIND_LABEL[x.type]) : x.type}
              </span>
              <span className='min-w-0 flex-1 truncate'>
                <span className='me-1.5 text-xs text-muted-foreground tabular-nums'>
                  #{x.ref}
                </span>
                {x.subject}
              </span>
              {x.status && (
                <span className='hidden items-center gap-1.5 text-xs text-muted-foreground sm:inline-flex'>
                  <StatusDot color={x.status_color ?? '#999'} />
                  {x.status}
                </span>
              )}
              <span className='hidden w-32 truncate text-end text-xs text-muted-foreground md:block'>
                {x.project_name}
              </span>
            </Link>
          )}
        </li>
      ))}
    </ul>
  )
}

function Contacts({ userId }: { userId: Id }) {
  const { t } = useTranslation('home')
  const contacts = useQuery({
    queryKey: ['profile-contacts', userId],
    queryFn: async () =>
      (await api.get<PublicUser[]>(`/users/${userId}/contacts`)).data,
  })
  if (contacts.isPending) return <Skeleton className='h-24 w-full' />
  if (!contacts.data?.length)
    return (
      <p className='text-sm text-muted-foreground'>{t('profile.noContacts')}</p>
    )
  return (
    <ul className='grid gap-2 sm:grid-cols-2'>
      {contacts.data.map((c) => (
        <li key={c.id}>
          <Link
            to='/profile/$username'
            params={{ username: c.username }}
            className='flex items-center gap-3 rounded-lg border bg-card p-3 hover:bg-accent/50'
          >
            <UserAvatar user={c} className='size-9' />
            <span className='min-w-0'>
              <span className='block truncate text-sm font-medium'>
                {c.full_name_display}
              </span>
              <span className='block truncate text-xs text-muted-foreground'>
                @{c.username}
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}
