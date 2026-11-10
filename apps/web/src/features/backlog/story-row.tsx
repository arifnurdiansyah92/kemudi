import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical, MoreHorizontal } from 'lucide-react'
import { useMoveToSprint } from '@/lib/taiga/queries'
import type { Milestone, Project, UserStory } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { can, useRefParam } from '@/features/project/use-project'
import {
  AssigneeMenu,
  Points,
  StatusMenu,
  TagList,
} from '@/features/story/parts'

type StoryRowProps = {
  project: Project
  story: UserStory
  sprints: Milestone[]
  sortable?: boolean
  /** Narrow layout for the sprint panel: no tags, status as a dot. */
  compact?: boolean
}

export function StoryRow({
  project,
  story,
  sprints,
  sortable = false,
  compact = false,
}: StoryRowProps) {
  const { open } = useRefParam()
  const move = useMoveToSprint(project)
  const editable = can(project, 'modify_us')
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: story.id, disabled: !sortable || !editable })

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        'group relative flex items-center gap-3 bg-card px-3 py-2 text-sm',
        isDragging && 'z-10 shadow-lg ring-1 ring-border',
        story.is_closed && 'text-muted-foreground'
      )}
    >
      {compact ? null : sortable && editable ? (
        <button
          ref={setActivatorNodeRef}
          {...attributes}
          {...listeners}
          aria-label={`Reorder #${story.ref}`}
          className='-ms-1 cursor-grab rounded p-0.5 text-muted-foreground/50 outline-none group-hover:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing'
        >
          <GripVertical className='size-4' />
        </button>
      ) : (
        <span className='w-4' aria-hidden='true' />
      )}

      <span className='w-10 shrink-0 text-xs text-muted-foreground tabular-nums'>
        #{story.ref}
      </span>

      <button
        onClick={() => open(story.ref)}
        className={cn(
          'min-w-0 flex-1 truncate text-start outline-none hover:underline hover:underline-offset-4 focus-visible:underline',
          story.is_closed && 'line-through decoration-muted-foreground/60'
        )}
      >
        {story.subject}
      </button>

      {!compact && (
        <span className='hidden lg:inline-flex'>
          <TagList project={project} tags={story.tags} max={2} />
        </span>
      )}
      <StatusMenu
        project={project}
        story={story}
        compact={compact}
        className={compact ? undefined : 'max-sm:hidden'}
      />
      <span className={cn('text-end text-sm', compact ? 'w-6' : 'w-8')}>
        <Points value={story.total_points} />
      </span>
      <AssigneeMenu project={project} story={story} />

      {editable && (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button
              variant='ghost'
              size='icon'
              className='size-7 text-muted-foreground'
              aria-label={`More actions for #${story.ref}`}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end' className='min-w-48'>
            <DropdownMenuItem onSelect={() => open(story.ref)}>
              Open story
            </DropdownMenuItem>
            {(sprints.length > 0 || story.milestone) && (
              <DropdownMenuSeparator />
            )}
            {sprints.length > 0 && (
              <DropdownMenuLabel className='text-xs font-normal text-muted-foreground'>
                Move to
              </DropdownMenuLabel>
            )}
            {sprints
              .filter((s) => s.id !== story.milestone)
              .map((sprint) => (
                <DropdownMenuItem
                  key={sprint.id}
                  onSelect={() =>
                    move.mutate({ story, milestoneId: sprint.id })
                  }
                >
                  {sprint.name}
                </DropdownMenuItem>
              ))}
            {story.milestone && (
              <DropdownMenuItem
                onSelect={() => move.mutate({ story, milestoneId: null })}
              >
                Backlog
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </li>
  )
}
