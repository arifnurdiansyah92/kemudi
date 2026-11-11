import { Fragment, useMemo, useRef, useState } from 'react'
import { useFormat } from '@/i18n/format'
import {
  closestCenter,
  DndContext,
  pointerWithin,
  type CollisionDetection,
  DragOverlay,
  KeyboardSensor,
  useDroppable,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useBacklogReorder,
  useMilestones,
  useMoveToSprint,
  useStories,
} from '@/lib/taiga/queries'
import { useClosedSprints, useProjectStats } from '@/lib/taiga/sprints'
import type { UserStory } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import {
  applyFilters,
  emptyFilters,
  isFiltering,
} from '@/features/filters/apply'
import {
  assigneeFacet,
  epicFacet,
  statusFacet,
  tagFacet,
} from '@/features/filters/facets'
import { FilterBar } from '@/features/filters/filter-bar'
import { can, useProject } from '@/features/project/use-project'
import { QuickAdd } from '@/features/story/quick-add'
import { between, forecastIndex, sumPoints } from '@/features/story/utils'
import { BulkAddDialog } from './bulk-add-dialog'
import { NewSprintDialog } from './new-sprint-dialog'
import { ProjectStats } from './project-stats'
import { SprintPanel } from './sprint-panel'
import { StoryRow } from './story-row'

export function Backlog() {
  const { t } = useTranslation(['backlog', 'common'])
  const { number } = useFormat()
  const project = useProject()
  const stories = useStories(project.id)
  const milestones = useMilestones(project.id)
  const reorder = useBacklogReorder(project)
  const move = useMoveToSprint(project)
  const addRef = useRef<HTMLInputElement>(null)
  const [filters, setFilters] = useState(emptyFilters)
  const [showClosed, setShowClosed] = useState(false)
  const closedSprints = useClosedSprints(project.id, showClosed)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  const sprints = useMemo(
    () =>
      [...(milestones.data ?? [])].sort((a, b) =>
        a.estimated_start.localeCompare(b.estimated_start)
      ),
    [milestones.data]
  )

  const backlog = useMemo(
    () =>
      (stories.data ?? [])
        .filter((s) => s.milestone === null)
        .sort((a, b) => a.backlog_order - b.backlog_order),
    [stories.data]
  )

  const bySprint = useMemo(() => {
    const map = new Map<number, typeof backlog>()
    for (const s of stories.data ?? []) {
      if (s.milestone === null) continue
      const list = map.get(s.milestone) ?? []
      list.push(s)
      map.set(s.milestone, list)
    }
    for (const list of map.values())
      list.sort((a, b) => a.sprint_order - b.sprint_order)
    return map
  }, [stories.data])

  const facets = useMemo(
    () => [
      statusFacet<UserStory>(project.us_statuses),
      assigneeFacet<UserStory>(project),
      tagFacet(project, backlog),
      epicFacet(backlog),
    ],
    [project, backlog]
  )
  const filtering = isFiltering(filters)
  const shown = useMemo(
    () => applyFilters(backlog, facets, filters),
    [backlog, facets, filters]
  )

  const [dragging, setDragging] = useState<number | null>(null)
  const byId = useMemo(
    () => new Map((stories.data ?? []).map((s) => [s.id, s])),
    [stories.data]
  )
  const dragged = dragging ? byId.get(dragging) : undefined
  const stats = useProjectStats(project.id)
  // Index of the last backlog story that fits the next sprint at the
  // team speed; the forecast line goes after it.
  const forecastAfter = useMemo(
    () => forecastIndex(shown, stats.data?.speed ?? 0),
    [shown, stats.data?.speed]
  )

  function onDragEnd({ active, over }: DragEndEvent) {
    setDragging(null)
    if (!over || active.id === over.id) return
    const story = byId.get(Number(active.id))
    if (!story) return
    // Where it was dropped: a sprint panel, the backlog, or another story.
    const overId = String(over.id)
    const target = overId.startsWith('sprint:')
      ? Number(overId.slice(7))
      : overId === 'backlog'
        ? null
        : (byId.get(Number(over.id))?.milestone ?? null)
    if (target !== story.milestone) {
      if (can(project, 'modify_us')) move.mutate({ story, milestoneId: target })
      return
    }
    if (story.milestone !== null) return
    const from = backlog.findIndex((s) => s.id === active.id)
    const to = backlog.findIndex((s) => s.id === over.id)
    if (from < 0 || to < 0) return
    const next = arrayMove(backlog, from, to)
    const prev = next[to - 1]
    const after = next[to + 1]
    reorder.mutate({
      storyId: Number(active.id),
      afterId: prev?.id,
      beforeId: prev ? undefined : after?.id,
      optimisticOrder: between(prev?.backlog_order, after?.backlog_order),
    })
  }

  const loading = stories.isPending || milestones.isPending
  const canAdd = can(project, 'add_us')
  const canAddSprint = can(project, 'add_milestone')

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: t('common:terms.backlog') },
        ]}
      />
      <Main width='list'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-tight'>
              {t('common:terms.backlog')}
            </h1>
            {!loading && (
              <p className='mt-1 text-sm text-muted-foreground tabular-nums'>
                {t('backlog.summary', {
                  count: backlog.length,
                  points: number(sumPoints(backlog)),
                })}
              </p>
            )}
          </div>
          {canAdd && (
            <div className='flex gap-2'>
              <BulkAddDialog project={project} />
              <Button size='sm' onClick={() => addRef.current?.focus()}>
                <Plus />
                {t('backlog.newStory')}
              </Button>
            </div>
          )}
        </div>
        <div className='mt-5'>
          <ProjectStats project={project} />
        </div>

        {stories.isError ? (
          <p className='mt-8 text-sm'>
            {t('backlog.loadError')}{' '}
            <button
              className='underline underline-offset-4'
              onClick={() => stories.refetch()}
            >
              {t('common:actions.retry')}
            </button>
          </p>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={pointerFirst}
            onDragStart={({ active }) => setDragging(Number(active.id))}
            onDragCancel={() => setDragging(null)}
            onDragEnd={onDragEnd}
          >
            <div className='mt-8 grid grid-cols-[minmax(0,1fr)] items-start gap-8 xl:grid-cols-[minmax(0,1fr)_24rem]'>
              <section aria-labelledby='backlog-heading' className='min-w-0'>
                <h2 id='backlog-heading' className='sr-only'>
                  {t('backlog.heading')}
                </h2>
                <FilterBar
                  savedKey={`${project.id}:kemudi-filters-backlog`}
                  items={backlog}
                  facets={facets}
                  value={filters}
                  onChange={setFilters}
                  className='mb-3'
                />
                <BacklogDrop>
                  {canAdd && (
                    <QuickAdd
                      project={project}
                      inputRef={addRef}
                      className='rounded-none border-b'
                    />
                  )}
                  {loading ? (
                    <div className='space-y-px p-2'>
                      {[0, 1, 2, 3].map((i) => (
                        <Skeleton key={i} className='h-9 w-full' />
                      ))}
                    </div>
                  ) : backlog.length === 0 ? (
                    <p className='px-4 py-10 text-center text-sm text-muted-foreground'>
                      {t('backlog.empty')}{' '}
                      {canAdd && t('backlog.emptyAddFirst')}
                    </p>
                  ) : shown.length === 0 ? (
                    <p className='px-4 py-10 text-center text-sm text-muted-foreground'>
                      {t('backlog.noMatch')}
                    </p>
                  ) : (
                    <SortableContext
                      items={shown.map((s) => s.id)}
                      strategy={verticalListSortingStrategy}
                    >
                      <ul className='divide-y'>
                        {shown.map((story, i) => (
                          <Fragment key={story.id}>
                            <StoryRow
                              project={project}
                              story={story}
                              sprints={sprints}
                              // Reordering a filtered list would place stories
                              // relative to ones you cannot see.
                              sortable={!filtering}
                            />
                            {!filtering && i === forecastAfter && (
                              <li
                                role='separator'
                                className='flex items-center gap-2 bg-muted/50 px-3 py-1.5 text-xs text-muted-foreground'
                              >
                                <span className='h-px flex-1 bg-brass/60' />
                                {t('backlog.forecastLine', {
                                  speed: number(stats.data?.speed ?? 0),
                                })}
                                <span className='h-px flex-1 bg-brass/60' />
                              </li>
                            )}
                          </Fragment>
                        ))}
                      </ul>
                    </SortableContext>
                  )}
                </BacklogDrop>
              </section>

              <section
                aria-labelledby='sprints-heading'
                className='space-y-3 xl:sticky xl:top-20'
              >
                <div className='flex items-center justify-between'>
                  <h2 id='sprints-heading' className='font-semibold'>
                    {t('sprint.openSprints')}
                  </h2>
                  {canAddSprint && (
                    <NewSprintDialog project={project} sprints={sprints} />
                  )}
                </div>
                {loading ? (
                  <Skeleton className='h-24 w-full' />
                ) : sprints.length === 0 ? (
                  <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
                    {t('sprint.noOpen')}
                  </p>
                ) : (
                  sprints.map((sprint, i) => (
                    <SprintPanel
                      key={sprint.id}
                      project={project}
                      sprint={sprint}
                      sprints={sprints}
                      stories={bySprint.get(sprint.id) ?? []}
                      defaultOpen={i === 0}
                    />
                  ))
                )}
                {showClosed ? (
                  <div className='space-y-3 pt-3'>
                    <h2 className='font-semibold'>
                      {t('sprint.closedSprints')}
                    </h2>
                    {closedSprints.isPending ? (
                      <Skeleton className='h-16 w-full' />
                    ) : (closedSprints.data ?? []).length === 0 ? (
                      <p className='text-sm text-muted-foreground'>
                        {t('sprint.noClosed')}
                      </p>
                    ) : (
                      closedSprints.data!.map((sprint) => (
                        <SprintPanel
                          key={sprint.id}
                          project={project}
                          sprint={sprint}
                          sprints={sprints}
                          stories={bySprint.get(sprint.id) ?? []}
                          defaultOpen={false}
                        />
                      ))
                    )}
                  </div>
                ) : (
                  <Button
                    variant='ghost'
                    size='sm'
                    className='text-muted-foreground'
                    onClick={() => setShowClosed(true)}
                  >
                    {t('sprint.showClosed')}
                  </Button>
                )}
              </section>
            </div>
            <DragOverlay>
              {dragged && (
                <div className='rounded-md border bg-card px-3 py-2 text-sm shadow-lg'>
                  <span className='me-2 text-xs text-muted-foreground tabular-nums'>
                    #{dragged.ref}
                  </span>
                  {dragged.subject}
                </div>
              )}
            </DragOverlay>
          </DndContext>
        )}
      </Main>
    </>
  )
}

/**
 * What is under the pointer decides the drop, stories before the boxes
 * that hold them. The dragged row's centre can sit far from the pointer
 * (rows are wide and grabbed at their left edge), which made a plain
 * centre-distance check pick a sprint for an in-list move.
 */
const pointerFirst: CollisionDetection = (args) => {
  const under = pointerWithin(args)
  if (under.length === 0) return closestCenter(args)
  const stories = under.filter((c) => typeof c.id === 'number')
  return stories.length ? stories : under
}

/** The backlog box; sprint stories dropped on it go back to the backlog. */
function BacklogDrop({ children }: { children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: 'backlog' })
  return (
    <div
      ref={setNodeRef}
      className={cn(
        'overflow-hidden rounded-lg border bg-card transition-shadow',
        isOver && 'ring-2 ring-ring'
      )}
    >
      {children}
    </div>
  )
}
