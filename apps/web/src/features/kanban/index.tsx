import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useFormat } from '@/i18n/format'
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
  type UniqueIdentifier,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { ChevronsLeftRight, ChevronsRightLeft } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import { useKanbanMove, useStories } from '@/lib/taiga/queries'
import type {
  Id,
  Project,
  Status,
  Swimlane,
  UserStory,
} from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { applyFilters, emptyFilters } from '@/features/filters/apply'
import { assigneeFacet, epicFacet, tagFacet } from '@/features/filters/facets'
import { FilterBar } from '@/features/filters/filter-bar'
import { can, useProject } from '@/features/project/use-project'
import { StatusDot } from '@/features/story/parts'
import { QuickAdd } from '@/features/story/quick-add'
import { between, sumPoints } from '@/features/story/utils'
import { CardFace, StoryCard, type Density } from './story-card'
import { useDensity, useFolded } from './use-folded'

/** Cells keyed `${swimlane or 0}:${status}`. */
type Cells = Record<string, Id[]>
const cellKey = (lane: Id | null, status: Id) => `${lane ?? 0}:${status}`

const densities: Density[] = ['compact', 'standard', 'detailed']

function useSwimlanes(projectId: Id) {
  return useQuery({
    queryKey: ['swimlanes', projectId],
    queryFn: async () =>
      (
        await api.get<Swimlane[]>('/swimlanes', {
          params: { project: projectId },
        })
      ).data.sort((a, b) => a.order - b.order),
  })
}

function useArchivedStories(projectId: Id, enabled: boolean) {
  return useQuery({
    queryKey: ['stories', projectId, 'archived'],
    enabled,
    queryFn: async () =>
      (
        await api.get<UserStory[]>('/userstories', {
          params: { project: projectId, status__is_archived: true },
          headers: { 'x-disable-pagination': '1' },
        })
      ).data,
  })
}

export function Kanban() {
  const { t } = useTranslation(['board', 'common'])
  const project = useProject()
  const stories = useStories(project.id)
  const lanes = useSwimlanes(project.id)
  const [showArchived, setShowArchived] = useState(false)
  const archived = useArchivedStories(project.id, showArchived)
  const move = useKanbanMove(project)
  const editable = can(project, 'modify_us')
  const { folded, toggle } = useFolded(project.id)
  const { density, setDensity } = useDensity(project.id)
  const [filters, setFilters] = useState(emptyFilters)

  const statuses = useMemo(
    () =>
      project.us_statuses
        .filter((s) => showArchived || !s.is_archived)
        .sort((a, b) => a.order - b.order),
    [project.us_statuses, showArchived]
  )

  const all = useMemo(
    () => [
      ...(stories.data ?? []),
      ...(showArchived ? (archived.data ?? []) : []),
    ],
    [stories.data, archived.data, showArchived]
  )
  const facets = useMemo(
    () => [
      assigneeFacet<UserStory>(project),
      tagFacet(project, all),
      epicFacet(all),
    ],
    [project, all]
  )
  const visible = useMemo(
    () => applyFilters(all, facets, filters),
    [all, facets, filters]
  )
  const byId = useMemo(() => new Map(all.map((s) => [s.id, s])), [all])

  // Lanes: each swimlane, plus "no swimlane" when stories have none.
  const laneList = useMemo(() => {
    const list: { id: Id | null; name: string }[] = (lanes.data ?? []).map(
      (l) => ({
        id: l.id,
        name: l.name,
      })
    )
    if (list.length === 0 || all.some((s) => s.swimlane === null))
      list.push({ id: null, name: list.length ? t('kanban.noSwimlane') : '' })
    return list
  }, [lanes.data, all, t])

  const cells = useMemo(() => {
    const c: Cells = {}
    for (const lane of laneList)
      for (const status of statuses) c[cellKey(lane.id, status.id)] = []
    const sorted = [...visible].sort((a, b) => a.kanban_order - b.kanban_order)
    for (const s of sorted) {
      const lane = laneList.some((l) => l.id === s.swimlane) ? s.swimlane : null
      c[cellKey(lane, s.status)]?.push(s.id)
    }
    return c
  }, [visible, laneList, statuses])

  const [dragCells, setDragCells] = useState<Cells | null>(null)
  const [activeId, setActiveId] = useState<Id | null>(null)
  const view = dragCells ?? cells

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  const cellOf = (c: Cells, id: UniqueIdentifier) => {
    if (typeof id === 'string' && id.startsWith('cell:')) return id.slice(5)
    return Object.keys(c).find((k) => c[k].includes(Number(id)))
  }

  function onDragOver({ active, over }: DragOverEvent) {
    if (!over || !dragCells) return
    const from = cellOf(dragCells, active.id)
    const to = cellOf(dragCells, over.id)
    if (!from || !to || from === to) return
    setDragCells((c) => {
      if (!c) return c
      const target = [...c[to]]
      const at = target.indexOf(Number(over.id))
      target.splice(at >= 0 ? at : target.length, 0, Number(active.id))
      return {
        ...c,
        [from]: c[from].filter((id) => id !== Number(active.id)),
        [to]: target,
      }
    })
  }

  function onDragEnd({ active, over }: DragEndEvent) {
    const c = dragCells
    setActiveId(null)
    setDragCells(null)
    if (!over || !c) return
    const story = byId.get(Number(active.id))
    const to = cellOf(c, over.id)
    if (!story || !to) return

    let list = c[to]
    const from = list.indexOf(story.id)
    const at = list.indexOf(Number(over.id))
    if (at >= 0 && at !== from) list = arrayMove(list, from, at)
    const index = list.indexOf(story.id)
    const prev = byId.get(list[index - 1])
    const next = byId.get(list[index + 1])

    const [lane, statusId] = to.split(':').map(Number)
    const swimlaneId = lane === 0 ? null : lane
    // Stories in a swimlane that no longer exists sit in the "none" lane.
    const currentLane = laneList.some((l) => l.id === story.swimlane)
      ? story.swimlane
      : null
    const original = cells[to]
    const unchanged =
      story.status === statusId &&
      currentLane === swimlaneId &&
      original[original.indexOf(story.id) - 1] === prev?.id
    if (unchanged) return

    move.mutate({
      story,
      statusId,
      // Without swimlanes, leave the story's swimlane alone.
      swimlaneId: currentLane === swimlaneId ? story.swimlane : swimlaneId,
      afterId: prev?.id,
      beforeId: prev ? undefined : next?.id,
      optimisticOrder: between(prev?.kanban_order, next?.kanban_order),
    })
  }

  const active = activeId ? byId.get(activeId) : undefined
  const loading = stories.isPending || lanes.isPending

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: t('common:terms.kanban') },
        ]}
      />
      <Main fixed fluid className='pb-0'>
        <h1 className='sr-only'>{t('common:terms.kanban')}</h1>
        <div className='mb-3 flex flex-wrap items-start justify-between gap-3'>
          <FilterBar
            savedKey={`${project.id}:kemudi-filters-kanban`}
            items={all}
            facets={facets}
            value={filters}
            onChange={setFilters}
            className='min-w-0 flex-1'
          />
          <div
            role='radiogroup'
            aria-label={t('kanban.density.label')}
            className='flex h-8 items-center rounded-md border p-0.5 text-xs'
          >
            {densities.map((d) => (
              <button
                key={d}
                role='radio'
                aria-checked={density === d}
                onClick={() => setDensity(d)}
                className={cn(
                  'h-full rounded px-2 capitalize',
                  density === d
                    ? 'bg-accent font-medium'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {t(`kanban.density.${d}`)}
              </button>
            ))}
          </div>
          {project.us_statuses.some((s) => s.is_archived) && (
            <label className='flex h-8 items-center gap-2 text-sm text-muted-foreground'>
              <Switch
                checked={showArchived}
                onCheckedChange={setShowArchived}
              />
              {t('kanban.showArchived')}
            </label>
          )}
        </div>

        {stories.isError ? (
          <p className='text-sm'>
            {t('kanban.loadError')}{' '}
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
            collisionDetection={closestCorners}
            // dnd-kit scrolls when the pointer is in the outer 20% of the
            // board by default. Columns near the edge sit inside that zone,
            // so a short drag there scrolled the next column under the
            // pointer and dropped the card in it. Scroll only at the very edge.
            autoScroll={{ threshold: { x: 0.05, y: 0.1 }, acceleration: 6 }}
            onDragStart={({ active }) => {
              setActiveId(Number(active.id))
              setDragCells(cells)
            }}
            onDragOver={onDragOver}
            onDragEnd={onDragEnd}
            onDragCancel={() => {
              setActiveId(null)
              setDragCells(null)
            }}
          >
            <div className='-mx-4 flex flex-1 flex-col gap-4 overflow-auto px-4 pb-4'>
              {laneList.map((lane) => (
                <section
                  key={lane.id ?? 'none'}
                  aria-label={lane.name || undefined}
                  // One lane fills the board and scrolls per column; with
                  // several, each lane keeps its full height and the board
                  // scrolls, so lanes never overlap.
                  className={cn(
                    'flex flex-col',
                    laneList.length === 1 ? 'min-h-0 flex-1' : 'shrink-0'
                  )}
                >
                  {lane.name && (
                    <h2 className='sticky start-0 mb-2 text-sm font-semibold'>
                      {lane.name}
                    </h2>
                  )}
                  <div
                    className={cn(
                      'flex gap-3',
                      laneList.length === 1 && 'flex-1'
                    )}
                  >
                    {statuses.map((status) => (
                      <Column
                        key={status.id}
                        project={project}
                        status={status}
                        lane={lane.id}
                        laneName={lane.name}
                        stories={
                          loading
                            ? undefined
                            : (view[cellKey(lane.id, status.id)] ?? [])
                                .map((id) => byId.get(id))
                                .filter((s): s is UserStory => !!s)
                        }
                        editable={editable}
                        folded={folded.has(status.id)}
                        density={density}
                        onToggleFold={() => toggle(status.id)}
                        fill={laneList.length === 1}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
            <DragOverlay>
              {active && (
                <CardFace
                  project={project}
                  story={active}
                  density={density}
                  lifted
                />
              )}
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
  lane,
  laneName,
  stories,
  editable,
  folded,
  onToggleFold,
  fill,
  density,
}: {
  project: Project
  status: Status
  lane: Id | null
  laneName: string
  stories: UserStory[] | undefined
  editable: boolean
  folded: boolean
  onToggleFold: () => void
  fill: boolean
  density: Density
}) {
  const { setNodeRef, isOver } = useDroppable({
    id: `cell:${cellKey(lane, status.id)}`,
  })
  const { t } = useTranslation(['board', 'common'])
  const format = useFormat()
  const canAdd = can(project, 'add_us')
  const count = stories?.length ?? 0
  const overWip = !!status.wip_limit && count > status.wip_limit
  const label = laneName
    ? t('kanban.column.inLane', { status: status.name, lane: laneName })
    : status.name

  if (folded)
    return (
      <section
        ref={setNodeRef}
        aria-label={t('kanban.column.folded', { label })}
        className={cn(
          'flex w-10 shrink-0 flex-col items-center gap-2 rounded-lg bg-muted/70 py-3',
          isOver && 'bg-accent'
        )}
      >
        <Button
          variant='ghost'
          size='icon'
          className='size-7'
          aria-label={t('kanban.column.unfold', { status: status.name })}
          onClick={onToggleFold}
        >
          <ChevronsLeftRight />
        </Button>
        <StatusDot color={status.color} />
        <span className='text-xs text-muted-foreground tabular-nums'>
          {count}
        </span>
        <span className='text-sm font-semibold [writing-mode:vertical-rl]'>
          {status.name}
        </span>
      </section>
    )

  return (
    <section
      aria-label={label}
      className={cn(
        'flex w-72 shrink-0 flex-col rounded-lg bg-muted/70',
        status.is_archived && 'opacity-80'
      )}
    >
      <header className='flex items-center gap-2 px-3 pt-3 pb-2'>
        <StatusDot color={status.color} />
        <h3 className='truncate text-sm font-semibold'>{status.name}</h3>
        <span
          className={cn(
            'text-xs text-muted-foreground tabular-nums',
            overWip && 'font-semibold text-destructive'
          )}
          title={overWip ? t('kanban.column.overWip') : undefined}
        >
          {count}
          {status.wip_limit ? ` / ${status.wip_limit}` : ''}
        </span>
        {stories && sumPoints(stories) > 0 && (
          <span className='text-xs text-muted-foreground tabular-nums'>
            {t('kanban.column.points', {
              count: sumPoints(stories),
              points: format.number(sumPoints(stories)),
            })}
          </span>
        )}
        <Button
          variant='ghost'
          size='icon'
          className='ms-auto size-6 text-muted-foreground'
          aria-label={t('kanban.column.fold', { status: status.name })}
          onClick={onToggleFold}
        >
          <ChevronsRightLeft />
        </Button>
      </header>

      <div
        ref={setNodeRef}
        className={cn(
          'min-h-24 overflow-y-auto px-2 pb-2',
          fill && 'flex-1',
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
                  density={density}
                />
              ))}
            </ul>
          </SortableContext>
        )}
      </div>

      {canAdd && !status.is_archived && (
        <QuickAdd
          project={project}
          status={status.id}
          swimlane={lane}
          placeholder={t('kanban.column.addTo', { status: status.name })}
          className='mx-2 mb-2'
        />
      )}
    </section>
  )
}
