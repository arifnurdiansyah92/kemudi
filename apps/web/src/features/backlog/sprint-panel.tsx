import { useState } from 'react'
import { format, parseISO } from 'date-fns'
import { ChevronRight } from 'lucide-react'
import type { Milestone, Project, UserStory } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { can } from '@/features/project/use-project'
import { QuickAdd } from '@/features/story/quick-add'
import { sumPoints } from '@/features/story/utils'
import { StoryRow } from './story-row'

function dateRange(sprint: Milestone) {
  const start = parseISO(sprint.estimated_start)
  const end = parseISO(sprint.estimated_finish)
  return `${format(start, 'd MMM')} – ${format(end, 'd MMM yyyy')}`
}

type SprintPanelProps = {
  project: Project
  sprint: Milestone
  stories: UserStory[]
  sprints: Milestone[]
  defaultOpen?: boolean
}

export function SprintPanel({
  project,
  sprint,
  stories,
  sprints,
  defaultOpen = true,
}: SprintPanelProps) {
  const [open, setOpen] = useState(defaultOpen)
  const total = sumPoints(stories)
  const done = sumPoints(stories.filter((s) => s.is_closed))
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className='overflow-hidden rounded-lg border bg-card'
    >
      <CollapsibleTrigger className='flex w-full items-center gap-3 px-4 py-3 text-start outline-none hover:bg-accent/50 focus-visible:bg-accent'>
        <ChevronRight
          aria-hidden='true'
          className={cn(
            'size-4 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-90'
          )}
        />
        <span className='min-w-0 flex-1'>
          <span className='block truncate font-medium'>{sprint.name}</span>
          <span className='block text-xs text-muted-foreground tabular-nums'>
            {dateRange(sprint)}
          </span>
        </span>
        <span className='shrink-0 text-end text-xs tabular-nums'>
          <span className='font-medium'>
            {done} of {total} pts
          </span>
          <span className='block text-muted-foreground'>
            {stories.length} {stories.length === 1 ? 'story' : 'stories'}
          </span>
        </span>
      </CollapsibleTrigger>
      <div
        className='h-1 bg-muted'
        role='progressbar'
        aria-label={`${sprint.name} progress`}
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className='h-full bg-success transition-[width]'
          style={{ width: `${pct}%` }}
        />
      </div>
      <CollapsibleContent>
        {stories.length > 0 ? (
          <ul className='divide-y border-b'>
            {stories.map((story) => (
              <StoryRow
                key={story.id}
                project={project}
                story={story}
                sprints={sprints}
                compact
              />
            ))}
          </ul>
        ) : (
          <p className='border-b px-4 py-4 text-sm text-muted-foreground'>
            No stories in this sprint. Move some here from the backlog with each
            story's menu.
          </p>
        )}
        {can(project, 'add_us') && (
          <QuickAdd
            project={project}
            milestone={sprint.id}
            placeholder={`Add a story to ${sprint.name}`}
            className='rounded-none'
          />
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
