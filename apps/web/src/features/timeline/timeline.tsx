import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '@/lib/taiga/client'
import { timeAgo } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { UserAvatar } from '@/components/user-avatar'
import { describe, visibleKey } from '@/features/item/history-text'

type Ref = {
  id: number
  ref?: number
  subject?: string
  slug?: string
  name?: string
}

export interface TimelineEvent {
  id: number
  event_type: string
  created: string
  data: {
    user?: { id: number; name: string; photo: string | null; username: string }
    project?: { id: number; name: string; slug: string }
    comment?: string
    comment_html?: string
    values_diff?: Record<string, unknown>
    userstory?: Ref
    task?: Ref
    issue?: Ref
    epic?: Ref
    wikipage?: Ref
    milestone?: Ref
    member?: { id: number; name: string }
  }
}

/** project/<id>, user/<id> (what the user did) or profile/<id> (what they follow). */
export type TimelineSource = `${'project' | 'user' | 'profile'}/${number}`

const NOUN: Record<string, string> = {
  userstory: 'story',
  task: 'task',
  issue: 'issue',
  epic: 'epic',
  wikipage: 'wiki page',
  milestone: 'sprint',
  project: 'project',
  membership: 'membership',
  relateduserstory: 'story',
}

function target(e: TimelineEvent) {
  const d = e.data
  const project = d.project?.slug
  for (const key of ['task', 'userstory', 'issue', 'epic'] as const) {
    const ref = d[key]
    if (ref?.ref && project)
      return {
        label: `#${ref.ref} ${ref.subject ?? ''}`.trim(),
        link: {
          to:
            key === 'issue'
              ? '/p/$slug/issues'
              : key === 'epic'
                ? '/p/$slug/epics'
                : '/p/$slug/backlog',
          params: { slug: project },
          search: { ref: ref.ref },
        },
      }
  }
  if (d.wikipage && project)
    return {
      label: d.wikipage.slug ?? '',
      link: {
        to: '/p/$slug/wiki/$page',
        params: { slug: project, page: d.wikipage.slug ?? 'home' },
      },
    }
  if (d.milestone && project)
    return {
      label: d.milestone.name ?? '',
      link: {
        to: '/p/$slug/taskboard/$sprint',
        params: { slug: project, sprint: String(d.milestone.id) },
      },
    }
  return null
}

/** "created story", "changed status from New to Ready on story", … */
function sentence(e: TimelineEvent) {
  const [, model, action] = e.event_type.split('.')
  const noun = NOUN[model] ?? model
  if (e.event_type === 'epics.relateduserstory.create')
    return {
      verb: 'added a story to epic',
      extra: e.data.epic ? `#${e.data.epic.ref} ${e.data.epic.subject}` : '',
    }
  if (model === 'membership')
    return { verb: 'added a member to the project', extra: '' }
  if (action === 'create') return { verb: `created ${noun}`, extra: '' }
  if (action === 'delete') return { verb: `deleted ${noun}`, extra: '' }
  if (e.data.comment) return { verb: `commented on ${noun}`, extra: '' }
  const changes = Object.entries(e.data.values_diff ?? {})
    .filter(([k]) => visibleKey(k))
    .map(([k, v]) => describe(k, v))
  return {
    verb: changes.length
      ? `${changes.join('; ')} on ${noun}`
      : `updated ${noun}`,
    extra: '',
  }
}

export function Timeline({
  source,
  showProject = false,
}: {
  source: TimelineSource
  showProject?: boolean
}) {
  const feed = useInfiniteQuery({
    queryKey: ['timeline', source],
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const res = await api.get<TimelineEvent[]>(`/timeline/${source}`, {
        params: { page: pageParam },
      })
      return { events: res.data, hasNext: !!res.headers['x-pagination-next'] }
    },
    getNextPageParam: (last, pages) =>
      last.hasNext ? pages.length + 1 : undefined,
  })

  if (feed.isPending)
    return (
      <div className='space-y-3'>
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className='h-12 w-full' />
        ))}
      </div>
    )
  const events = feed.data?.pages.flatMap((p) => p.events) ?? []
  if (events.length === 0)
    return (
      <p className='text-sm text-muted-foreground'>Nothing has happened yet.</p>
    )

  return (
    <div>
      <ol className='grid gap-4'>
        {events.map((e) => {
          const t = target(e)
          const { verb, extra } = sentence(e)
          const user = e.data.user
          return (
            <li key={e.id} className='flex gap-3 text-sm'>
              {user ? (
                <UserAvatar
                  user={{ photo: user.photo, full_name_display: user.name }}
                  className='mt-0.5 size-7'
                />
              ) : (
                <span className='size-7' />
              )}
              <div className='min-w-0 flex-1'>
                <p className='leading-snug'>
                  <span className='font-medium'>{user?.name ?? 'Someone'}</span>{' '}
                  <span className='text-muted-foreground'>{verb}</span>{' '}
                  {t &&
                    (t.link ? (
                      <Link
                        {...(t.link as { to: string })}
                        className='font-medium underline-offset-4 hover:underline'
                      >
                        {t.label}
                      </Link>
                    ) : (
                      t.label
                    ))}
                  {extra && (
                    <span className='text-muted-foreground'> {extra}</span>
                  )}
                </p>
                {e.data.comment_html && (
                  <div
                    className='rich-text mt-1 border-s-2 ps-3 text-muted-foreground'
                    dangerouslySetInnerHTML={{ __html: e.data.comment_html }}
                  />
                )}
                <p className='mt-0.5 text-xs text-muted-foreground'>
                  {timeAgo(e.created)}
                  {showProject &&
                    e.data.project &&
                    ` in ${e.data.project.name}`}
                </p>
              </div>
            </li>
          )
        })}
      </ol>
      {feed.hasNextPage && (
        <Button
          variant='outline'
          size='sm'
          className='mt-6'
          disabled={feed.isFetchingNextPage}
          onClick={() => feed.fetchNextPage()}
        >
          {feed.isFetchingNextPage ? 'Loading…' : 'Show older activity'}
        </Button>
      )}
    </div>
  )
}
