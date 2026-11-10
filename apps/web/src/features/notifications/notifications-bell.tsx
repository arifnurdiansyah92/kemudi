import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Bell } from 'lucide-react'
import {
  useMarkNotificationsRead,
  useNotifications,
  type WebNotification,
} from '@/lib/taiga/me'
import { cn, timeAgo } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { UserAvatar } from '@/components/user-avatar'

const VERB: Record<WebNotification['event_type'], string> = {
  1: 'assigned you to',
  2: 'mentioned you in',
  3: 'added you as a watcher of',
  4: 'added you to the project',
  5: 'commented on',
  6: 'mentioned you in a comment on',
}

const PAGE: Record<string, string> = {
  userstory: '/p/$slug/backlog',
  task: '/p/$slug/backlog',
  issue: '/p/$slug/issues',
  epic: '/p/$slug/epics',
}

export function NotificationsBell() {
  const navigate = useNavigate()
  const { data } = useNotifications()
  const mark = useMarkNotificationsRead()
  const list = data?.objects ?? []
  const unread = list.filter((n) => !n.read).length
  const [open, setOpen] = useState(false)

  const go = (n: WebNotification) => {
    setOpen(false)
    if (!n.read) mark.mutate(n)
    const slug = n.data.project?.slug
    if (!slug) return
    const obj = n.data.obj
    if (obj?.ref && PAGE[obj.content_type])
      navigate({
        to: PAGE[obj.content_type],
        params: { slug },
        search: { ref: obj.ref },
      })
    else navigate({ to: '/p/$slug', params: { slug } })
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant='ghost'
          size='icon'
          className='relative rounded-full'
          aria-label={
            unread ? `Notifications, ${unread} unread` : 'Notifications'
          }
        >
          <Bell className='size-[1.15rem]' />
          {unread > 0 && (
            <span className='absolute end-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-brass px-1 text-[0.625rem] font-semibold text-sidebar tabular-nums'>
              {unread > 9 ? '9+' : unread}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align='end' className='w-96 p-0'>
        <div className='flex items-center justify-between border-b px-4 py-2.5'>
          <h2 className='text-sm font-semibold'>Notifications</h2>
          {unread > 0 && (
            <Button
              variant='ghost'
              size='sm'
              className='h-7 text-xs'
              onClick={() => mark.mutate(undefined)}
            >
              Mark all as read
            </Button>
          )}
        </div>
        {list.length === 0 ? (
          <p className='px-4 py-8 text-center text-sm text-muted-foreground'>
            Nothing new. You hear about assignments, mentions and comments here.
          </p>
        ) : (
          <ul className='max-h-[60vh] divide-y overflow-y-auto'>
            {list.map((n) => {
              const obj = n.data.obj
              return (
                <li key={n.id}>
                  <button
                    onClick={() => go(n)}
                    className={cn(
                      'flex w-full gap-3 px-4 py-3 text-start text-sm hover:bg-accent/60',
                      !n.read && 'bg-accent/30'
                    )}
                  >
                    <UserAvatar
                      user={{
                        photo: n.data.user?.photo ?? null,
                        full_name_display: n.data.user?.name ?? '?',
                      }}
                      className='mt-0.5 size-7'
                    />
                    <span className='min-w-0 flex-1'>
                      <span className='block leading-snug'>
                        <span className='font-medium'>{n.data.user?.name}</span>{' '}
                        <span className='text-muted-foreground'>
                          {VERB[n.event_type]}
                        </span>{' '}
                        {obj?.ref ? (
                          <span className='font-medium'>
                            #{obj.ref} {obj.subject}
                          </span>
                        ) : (
                          <span className='font-medium'>
                            {n.data.project?.name}
                          </span>
                        )}
                      </span>
                      <span className='mt-0.5 block text-xs text-muted-foreground'>
                        {timeAgo(n.created)}
                        {obj?.ref &&
                          n.data.project &&
                          ` in ${n.data.project.name}`}
                      </span>
                    </span>
                    {!n.read && (
                      <span
                        className='mt-2 size-2 shrink-0 rounded-full bg-brass'
                        aria-label='Unread'
                      />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  )
}
