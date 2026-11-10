import { useMemo, useRef } from 'react'
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { Plus } from 'lucide-react'
import {
  useBacklogReorder,
  useMilestones,
  useStories,
} from '@/lib/taiga/queries'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { can, useProject } from '@/features/project/use-project'
import { QuickAdd } from '@/features/story/quick-add'
import { between, sumPoints } from '@/features/story/utils'
import { NewSprintDialog } from './new-sprint-dialog'
import { SprintPanel } from './sprint-panel'
import { StoryRow } from './story-row'

export function Backlog() {
  const project = useProject()
  const stories = useStories(project.id)
  const milestones = useMilestones(project.id)
  const reorder = useBacklogReorder(project)
  const addRef = useRef<HTMLInputElement>(null)

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

  function onDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return
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

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: 'Backlog' },
        ]}
      />
      <Main fluid className='mx-auto w-full max-w-6xl'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-tight'>Backlog</h1>
            {!loading && (
              <p className='mt-1 text-sm text-muted-foreground tabular-nums'>
                {backlog.length} {backlog.length === 1 ? 'story' : 'stories'},{' '}
                {sumPoints(backlog)} points waiting for a sprint
              </p>
            )}
          </div>
          {canAdd && (
            <Button size='sm' onClick={() => addRef.current?.focus()}>
              <Plus />
              New story
            </Button>
          )}
        </div>

        {stories.isError ? (
          <p className='mt-8 text-sm'>
            Stories could not be loaded.{' '}
            <button
              className='underline underline-offset-4'
              onClick={() => stories.refetch()}
            >
              Try again
            </button>
          </p>
        ) : (
          <div className='mt-8 grid grid-cols-[minmax(0,1fr)] items-start gap-8 xl:grid-cols-[minmax(0,1fr)_24rem]'>
            <section aria-labelledby='backlog-heading' className='min-w-0'>
              <h2 id='backlog-heading' className='sr-only'>
                Stories not in a sprint
              </h2>
              <div className='overflow-hidden rounded-lg border bg-card'>
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
                    The backlog is empty.{' '}
                    {canAdd && 'Add the first story above.'}
                  </p>
                ) : (
                  <DndContext
                    sensors={sensors}
                    collisionDetection={closestCenter}
                    modifiers={[restrictToVerticalAxis]}
                    onDragEnd={onDragEnd}
                  >
                    <SortableContext
                      items={backlog.map((s) => s.id)}
                      strategy={verticalListSortingStrategy}
                    >
                      <ul className='divide-y'>
                        {backlog.map((story) => (
                          <StoryRow
                            key={story.id}
                            project={project}
                            story={story}
                            sprints={sprints}
                            sortable
                          />
                        ))}
                      </ul>
                    </SortableContext>
                  </DndContext>
                )}
              </div>
            </section>

            <section
              aria-labelledby='sprints-heading'
              className='space-y-3 xl:sticky xl:top-20'
            >
              <div className='flex items-center justify-between'>
                <h2 id='sprints-heading' className='font-semibold'>
                  Open sprints
                </h2>
                {can(project, 'add_milestone') && (
                  <NewSprintDialog project={project} sprints={sprints} />
                )}
              </div>
              {loading ? (
                <Skeleton className='h-24 w-full' />
              ) : sprints.length === 0 ? (
                <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
                  No open sprints. Create one to plan the next stretch of work.
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
            </section>
          </div>
        )}
      </Main>
    </>
  )
}
