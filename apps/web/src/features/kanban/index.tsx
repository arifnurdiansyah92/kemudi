import { useMemo, useState } from 'react'
import {
  closestCorners,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
  type UniqueIdentifier,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { useKanbanMove, useStories } from '@/lib/taiga/queries'
import type { Id, Project, Status, UserStory } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { can, useProject } from '@/features/project/use-project'
import { StatusDot } from '@/features/story/parts'
import { QuickAdd } from '@/features/story/quick-add'
import { between, sumPoints } from '@/features/story/utils'
import { CardFace, StoryCard } from './story-card'

type Columns = Record<string, Id[]>
const colId = (statusId: Id) => `col-${statusId}`

export function Kanban() {
  const project = useProject()
  const stories = useStories(project.id)
  const move = useKanbanMove(project)
  const editable = can(project, 'modify_us')

  const statuses = useMemo(
    () =>
      project.us_statuses
        .filter((s) => !s.is_archived)
        .sort((a, b) => a.order - b.order),
    [project.us_statuses]
  )
  const byId = useMemo(
    () => new Map((stories.data ?? []).map((s) => [s.id, s])),
    [stories.data]
  )

  const columns = useMemo(() => {
    const cols: Columns = {}
    for (const status of statuses) cols[status.id] = []
    const sorted = [...(stories.data ?? [])].sort(
      (a, b) => a.kanban_order - b.kanban_order
    )
    for (const s of sorted) cols[s.status]?.push(s.id)
    return cols
  }, [stories.data, statuses])

  // While dragging, cards move between columns locally; the server is only
  // told on drop.
  const [dragCols, setDragCols] = useState<Columns | null>(null)
  const [activeId, setActiveId] = useState<Id | null>(null)
  const view = dragCols ?? columns

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  function columnOf(cols: Columns, id: UniqueIdentifier) {
    if (typeof id === 'string' && id.startsWith('col-')) return id.slice(4)
    return Object.keys(cols).find((key) => cols[key].includes(Number(id)))
  }

  function onDragStart({ active }: DragStartEvent) {
    setActiveId(Number(active.id))
    setDragCols(columns)
  }

  function onDragOver({ active, over }: DragOverEvent) {
    if (!over || !dragCols) return
    const from = columnOf(dragCols, active.id)
    const to = columnOf(dragCols, over.id)
    if (!from || !to || from === to) return
    setDragCols((cols) => {
      if (!cols) return cols
      const source = cols[from].filter((id) => id !== Number(active.id))
      const target = [...cols[to]]
      const overIndex = target.indexOf(Number(over.id))
      target.splice(
        overIndex >= 0 ? overIndex : target.length,
        0,
        Number(active.id)
      )
      return { ...cols, [from]: source, [to]: target }
    })
  }

  function onDragEnd({ active, over }: DragEndEvent) {
    const cols = dragCols
    setActiveId(null)
    setDragCols(null)
    if (!over || !cols) return

    const storyId = Number(active.id)
    const story = byId.get(storyId)
    const to = columnOf(cols, over.id)
    if (!story || !to) return

    let list = cols[to]
    const oldIndex = list.indexOf(storyId)
    const overIndex = list.indexOf(Number(over.id))
    if (overIndex >= 0 && oldIndex !== overIndex)
      list = arrayMove(list, oldIndex, overIndex)
    const index = list.indexOf(storyId)

    const prev = byId.get(list[index - 1])
    const next = byId.get(list[index + 1])
    const statusId = Number(to)
    const unchanged =
      story.status === statusId &&
      columns[to][columns[to].indexOf(storyId) - 1] === prev?.id
    if (unchanged) return

    move.mutate({
      story,
      statusId,
      afterId: prev?.id,
      beforeId: prev ? undefined : next?.id,
      optimisticOrder: between(prev?.kanban_order, next?.kanban_order),
    })
  }

  const active = activeId ? byId.get(activeId) : undefined

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: 'Kanban' },
        ]}
      />
      <Main fixed fluid className='pb-0'>
        <h1 className='sr-only'>Kanban</h1>
        {stories.isError ? (
          <p className='text-sm'>
            Stories could not be loaded.{' '}
            <button
              className='underline underline-offset-4'
              onClick={() => stories.refetch()}
            >
              Try again
            </button>
          </p>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCorners}
            // dnd-kit scrolls when the pointer is in the outer 20% of the
            // board by default. Columns near the edge sit inside that zone,
            // so a short drag there scrolled the next column under the
            // pointer and dropped the card in it. Scroll only at the very edge.
            autoScroll={{ threshold: { x: 0.05, y: 0.1 }, acceleration: 6 }}
            onDragStart={onDragStart}
            onDragOver={onDragOver}
            onDragEnd={onDragEnd}
            onDragCancel={() => {
              setActiveId(null)
              setDragCols(null)
            }}
          >
            <div className='-mx-4 flex flex-1 gap-3 overflow-x-auto px-4 pb-4'>
              {statuses.map((status) => (
                <Column
                  key={status.id}
                  project={project}
                  status={status}
                  stories={
                    stories.isPending
                      ? undefined
                      : view[status.id]
                          .map((id) => byId.get(id))
                          .filter((s): s is UserStory => !!s)
                  }
                  editable={editable}
                />
              ))}
            </div>
            <DragOverlay>
              {active && <CardFace project={project} story={active} lifted />}
            </DragOverlay>
          </DndContext>
        )}
      </Main>
    </>
  )
}

function Column({
  project,
  status,
  stories,
  editable,
}: {
  project: Project
  status: Status
  stories: UserStory[] | undefined
  editable: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({ id: colId(status.id) })
  const count = stories?.length ?? 0
  const overWip = !!status.wip_limit && count > status.wip_limit

  return (
    <section
      aria-label={status.name}
      className='flex w-72 shrink-0 flex-col rounded-lg bg-muted/70'
    >
      <header className='flex items-center gap-2 px-3 pt-3 pb-2'>
        <StatusDot color={status.color} />
        <h2 className='truncate text-sm font-semibold'>{status.name}</h2>
        <span
          className={cn(
            'text-xs text-muted-foreground tabular-nums',
            overWip && 'font-semibold text-destructive'
          )}
          title={overWip ? 'Over the work-in-progress limit' : undefined}
        >
          {count}
          {status.wip_limit ? ` / ${status.wip_limit}` : ''}
        </span>
        {stories && sumPoints(stories) > 0 && (
          <span className='ms-auto text-xs text-muted-foreground tabular-nums'>
            {sumPoints(stories)} pts
          </span>
        )}
      </header>

      <div
        ref={setNodeRef}
        className={cn(
          'min-h-24 flex-1 overflow-y-auto px-2 pb-2',
          isOver && 'rounded-md bg-accent/60'
        )}
      >
        {stories === undefined ? (
          <div className='space-y-2'>
            <Skeleton className='h-20 w-full bg-card' />
            <Skeleton className='h-16 w-full bg-card' />
          </div>
        ) : (
          <SortableContext
            items={stories.map((s) => s.id)}
            strategy={verticalListSortingStrategy}
          >
            <ul className='space-y-2'>
              {stories.map((story) => (
                <StoryCard
                  key={story.id}
                  project={project}
                  story={story}
                  draggable={editable}
                />
              ))}
            </ul>
          </SortableContext>
        )}
      </div>

      {can(project, 'add_us') && (
        <QuickAdd
          project={project}
          status={status.id}
          placeholder={`Add to ${status.name}`}
          className='mx-2 mb-2'
        />
      )}
    </section>
  )
}
