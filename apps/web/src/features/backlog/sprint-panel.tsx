import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { ChevronRight, LayoutGrid } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
import { SprintMenu } from '@/features/taskboard/sprint-menu'
import { StoryRow } from './story-row'

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
  const { t } = useTranslation(['backlog', 'common'])
  const { dateRange } = useFormat()
  const [open, setOpen] = useState(defaultOpen)
  const { setNodeRef, isOver } = useDroppable({ id: `sprint:${sprint.id}` })
  const total = sumPoints(stories)
  const done = sumPoints(stories.filter((s) => s.is_closed))
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  const canAdd = can(project, 'add_us')

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      ref={setNodeRef}
      className={cn(
        'overflow-hidden rounded-lg border bg-card transition-shadow',
        isOver && 'ring-2 ring-ring'
      )}
    >
      <div className='flex items-center pe-2'>
        <CollapsibleTrigger className='flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-start outline-none hover:bg-accent/50 focus-visible:bg-accent'>
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
              {dateRange(sprint.estimated_start, sprint.estimated_finish)}
            </span>
          </span>
          <span className='shrink-0 text-end text-xs tabular-nums'>
            <span className='font-medium'>
              {t('sprint.panel.points', { done, total })}
            </span>
            <span className='block text-muted-foreground'>
              {t('story.count', { count: stories.length })}
            </span>
          </span>
        </CollapsibleTrigger>
        <Link
          to='/p/$slug/taskboard/$sprint'
          params={{ slug: project.slug, sprint: String(sprint.id) }}
          aria-label={t('sprint.panel.openTaskboard', { name: sprint.name })}
          title={t('common:terms.taskboard')}
          className='flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground'
        >
          <LayoutGrid className='size-4' />
        </Link>
        <SprintMenu project={project} sprint={sprint} />
      </div>
      <div
        className='h-1 bg-muted'
        role='progressbar'
        aria-label={t('sprint.panel.progress', { name: sprint.name })}
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
          <SortableContext
            items={stories.map((s) => s.id)}
            strategy={verticalListSortingStrategy}
          >
            <ul className='divide-y border-b'>
              {stories.map((story) => (
                <StoryRow
                  key={story.id}
                  project={project}
                  story={story}
                  sprints={sprints}
                  compact
                  sortable
                />
              ))}
            </ul>
          </SortableContext>
        ) : (
          <p className='border-b px-4 py-4 text-sm text-muted-foreground'>
            {t('sprint.panel.empty')}
          </p>
        )}
        {canAdd && (
          <QuickAdd
            project={project}
            milestone={sprint.id}
            placeholder={t('sprint.panel.addStory', { name: sprint.name })}
            className='rounded-none'
          />
        )}
      </CollapsibleContent>
    </Collapsible>
  )
}
