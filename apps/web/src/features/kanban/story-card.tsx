import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Ban } from 'lucide-react'
import type { Project, UserStory } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { UserAvatar } from '@/components/user-avatar'
import { useStoryParam } from '@/features/project/use-project'
import { Points, TagList } from '@/features/story/parts'

type StoryCardProps = {
  project: Project
  story: UserStory
  draggable: boolean
}

export function StoryCard({ project, story, draggable }: StoryCardProps) {
  const { open } = useStoryParam()
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
        {...attributes}
        {...listeners}
        aria-roledescription={draggable ? 'Draggable story' : undefined}
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

type CardFaceProps = React.HTMLAttributes<HTMLDivElement> & {
  project: Project
  story: UserStory
  lifted?: boolean
}

export function CardFace({
  project,
  story,
  lifted,
  className,
  ...props
}: CardFaceProps) {
  const assignee = project.members.find((m) => m.id === story.assigned_to)
  return (
    <div
      role='button'
      tabIndex={0}
      className={cn(
        'grid cursor-pointer gap-2 rounded-md border bg-card p-3 text-sm shadow-xs outline-none hover:border-foreground/20 focus-visible:ring-2 focus-visible:ring-ring',
        story.is_blocked && 'border-s-4 border-s-destructive',
        lifted && 'rotate-1 cursor-grabbing shadow-lg',
        className
      )}
      {...props}
    >
      <p className='line-clamp-3 leading-snug'>{story.subject}</p>
      {story.tags.length > 0 && (
        <TagList project={project} tags={story.tags} max={3} />
      )}
      <div className='flex items-center gap-2 text-xs text-muted-foreground'>
        <span className='tabular-nums'>#{story.ref}</span>
        {story.is_blocked && (
          <span className='inline-flex items-center gap-1 text-destructive'>
            <Ban className='size-3' />
            Blocked
          </span>
        )}
        <span className='ms-auto inline-flex items-center gap-2'>
          {story.total_points !== null && (
            <span className='rounded bg-muted px-1.5 py-0.5 font-medium text-foreground'>
              <Points value={story.total_points} />
              <span className='sr-only'> points</span>
            </span>
          )}
          {assignee && <UserAvatar user={assignee} className='size-5' />}
        </span>
      </div>
    </div>
  )
}
