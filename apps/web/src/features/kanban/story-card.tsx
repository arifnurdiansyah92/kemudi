import { useFormat } from '@/i18n/format'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Ban } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { Project, UserStory } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { UserAvatar } from '@/components/user-avatar'
import { useRefParam } from '@/features/project/use-project'
import { Points, TagList } from '@/features/story/parts'

type StoryCardProps = {
  project: Project
  story: UserStory
  draggable: boolean
  density?: Density
}

export function StoryCard({
  project,
  story,
  draggable,
  density,
}: StoryCardProps) {
  const { t } = useTranslation(['board', 'common'])
  const { open } = useRefParam()
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: story.id, disabled: !draggable })

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(isDragging && 'opacity-40')}
    >
      <CardFace
        project={project}
        story={story}
        density={density}
        {...attributes}
        {...listeners}
        aria-roledescription={
          draggable ? t('kanban.card.draggable') : undefined
        }
        onClick={() => open(story.ref)}
        onKeyDown={(e) => {
          // Space picks the card up (dnd-kit); Enter opens it.
          if (e.key === 'Enter') open(story.ref)
          else listeners?.onKeyDown?.(e)
        }}
      />
    </li>
  )
}

export type Density = 'compact' | 'standard' | 'detailed'

type CardFaceProps = React.HTMLAttributes<HTMLDivElement> & {
  project: Project
  story: UserStory
  lifted?: boolean
  density?: Density
}

export function CardFace({
  project,
  story,
  lifted,
  density = 'standard',
  className,
  ...props
}: CardFaceProps) {
  const { t } = useTranslation(['board', 'common'])
  const format = useFormat()
  const assignee = project.members.find((m) => m.id === story.assigned_to)
  const tasks = story.tasks ?? []
  const done = tasks.filter((t) => t.is_closed).length
  return (
    <div
      role='button'
      tabIndex={0}
      className={cn(
        'grid cursor-pointer rounded-md border bg-card text-sm shadow-xs outline-none hover:border-foreground/20 focus-visible:ring-2 focus-visible:ring-ring',
        density === 'compact' ? 'gap-1 px-2.5 py-1.5' : 'gap-2 p-3',
        story.is_blocked && 'border-destructive/40 bg-destructive/5',
        lifted && 'rotate-1 cursor-grabbing shadow-lg',
        className
      )}
      {...props}
    >
      {density === 'compact' ? (
        <p className='flex items-baseline gap-2 leading-snug'>
          <span className='shrink-0 text-xs text-muted-foreground tabular-nums'>
            #{story.ref}
          </span>
          <span className='line-clamp-2'>{story.subject}</span>
          {assignee && (
            <UserAvatar
              user={assignee}
              className='ms-auto size-4 shrink-0 self-center'
            />
          )}
        </p>
      ) : (
        <>
          <p className='line-clamp-3 leading-snug'>{story.subject}</p>
          {story.tags.length > 0 && (
            <TagList project={project} tags={story.tags} max={3} />
          )}
          {density === 'detailed' && (
            <div className='grid gap-1 text-xs text-muted-foreground'>
              {(story.epics ?? []).map((e) => (
                <span
                  key={e.id}
                  className='inline-flex items-center gap-1.5 truncate'
                >
                  <span
                    aria-hidden='true'
                    className='size-2 shrink-0 rounded-full'
                    style={{ backgroundColor: e.color }}
                  />
                  {e.subject}
                </span>
              ))}
              {tasks.length > 0 && (
                <span className='inline-flex items-center gap-2'>
                  <span
                    className='h-1 w-16 overflow-hidden rounded-full bg-muted'
                    aria-hidden='true'
                  >
                    <span
                      className='block h-full bg-success'
                      style={{ width: `${(done / tasks.length) * 100}%` }}
                    />
                  </span>
                  {t('kanban.card.tasksDone', { done, count: tasks.length })}
                </span>
              )}
              {story.due_date && (
                <span>
                  {t('kanban.card.due', { date: format.date(story.due_date) })}
                </span>
              )}
              {assignee && <span>{assignee.full_name_display}</span>}
            </div>
          )}
          <div className='flex items-center gap-2 text-xs text-muted-foreground'>
            <span className='tabular-nums'>#{story.ref}</span>
            {story.is_blocked && (
              <span className='inline-flex items-center gap-1 text-destructive'>
                <Ban className='size-3' />
                {t('kanban.card.blocked')}
              </span>
            )}
            <span className='ms-auto inline-flex items-center gap-2'>
              {story.total_points !== null && (
                <span className='rounded bg-muted px-1.5 py-0.5 font-medium text-foreground'>
                  <Points value={story.total_points} />
                  <span className='sr-only'> {t('kanban.card.points')}</span>
                </span>
              )}
              {assignee && <UserAvatar user={assignee} className='size-5' />}
            </span>
          </div>
        </>
      )}
    </div>
  )
}
