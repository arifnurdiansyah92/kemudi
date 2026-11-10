import { useMemo, useState } from 'react'
import { format } from 'date-fns'
import { Link, useNavigate } from '@tanstack/react-router'
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
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Ban, Check, ChevronDown, Flame, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useMilestones, useStories } from '@/lib/taiga/queries'
import {
  useBulkCreateTasks,
  useClosedSprints,
  useMoveTask,
  useSprint,
  useSprintStats,
  useSprintTasks,
  type SprintStats,
} from '@/lib/taiga/sprints'
import type { Id, Milestone, Project, Task, UserStory } from '@/lib/taiga/types'
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
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { UserAvatar } from '@/components/user-avatar'
import { can, useProject, useRefParam } from '@/features/project/use-project'
import { Points, StatusDot } from '@/features/story/parts'
import { Burndown } from './burndown'
import { SprintMenu } from './sprint-menu'

type Cells = Record<string, Id[]>
const cellKey = (storyId: Id | null, statusId: Id) =>
  `${storyId ?? 0}:${statusId}`

export function Taskboard({ sprintId }: { sprintId: Id }) {
  const { t } = useTranslation(['backlog', 'common'])
  const { dateRange, number } = useFormat()
  const project = useProject()
  const sprint = useSprint(sprintId)
  const tasks = useSprintTasks(project.id, sprintId)
  const stories = useStories(project.id)
  const stats = useSprintStats(sprintId)
  const move = useMoveTask(project, sprintId)
  const editable = can(project, 'modify_task')

  const statuses = useMemo(
    () => [...project.task_statuses].sort((a, b) => a.order - b.order),
    [project.task_statuses]
  )
  // Stories come from the project list so status changes elsewhere show here.
  const sprintStories = useMemo(
    () =>
      (stories.data ?? [])
        .filter((s) => s.milestone === sprintId)
        .sort((a, b) => a.sprint_order - b.sprint_order),
    [stories.data, sprintId]
  )
  const byId = useMemo(
    () => new Map((tasks.data ?? []).map((t) => [t.id, t])),
    [tasks.data]
  )

  const cells = useMemo(() => {
    const c: Cells = {}
    const rows: (Id | null)[] = [...sprintStories.map((s) => s.id), null]
    for (const row of rows)
      for (const status of statuses) c[cellKey(row, status.id)] = []
    const sorted = [...(tasks.data ?? [])].sort(
      (a, b) => a.taskboard_order - b.taskboard_order || a.ref - b.ref
    )
    for (const t of sorted) {
      const row = sprintStories.some((s) => s.id === t.user_story)
        ? t.user_story
        : null
      c[cellKey(row, t.status)]?.push(t.id)
    }
    return c
  }, [tasks.data, sprintStories, statuses])

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
    setDragCells(null)
    setActiveId(null)
    if (!over || !c) return
    const task = byId.get(Number(active.id))
    const to = cellOf(c, over.id)
    if (!task || !to) return
    let list = c[to]
    const from = list.indexOf(task.id)
    const at = list.indexOf(Number(over.id))
    if (at >= 0 && at !== from) list = arrayMove(list, from, at)
    const [row, status] = to.split(':').map(Number)
    const storyId = row === 0 ? null : row
    const original = cells[to]
    const unchanged =
      task.status === status &&
      (task.user_story ?? null) === storyId &&
      original.join() === list.join()
    if (unchanged) return
    move.mutate({ task, statusId: status, storyId, cell: list })
  }

  if (sprint.isError)
    return (
      <>
        <AppHeader
          crumbs={[
            { label: project.name },
            { label: t('common:terms.taskboard') },
          ]}
        />
        <Main>
          <p className='text-sm'>
            {t('taskboard.notFound')}{' '}
            <Link
              to='/p/$slug/backlog'
              params={{ slug: project.slug }}
              className='underline underline-offset-4'
            >
              {t('taskboard.backToBacklog')}
            </Link>
          </p>
        </Main>
      </>
    )

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
          { label: t('common:terms.taskboard') },
        ]}
      />
      <Main fluid className='pb-0'>
        <div className='flex flex-wrap items-start justify-between gap-6'>
          <div className='min-w-0'>
            <div className='flex items-center gap-1'>
              <SprintSwitcher
                project={project}
                current={sprint.data}
                sprintId={sprintId}
              />
              {sprint.data && (
                <SprintMenu project={project} sprint={sprint.data} />
              )}
            </div>
            {sprint.data && (
              <p className='mt-1 text-sm text-muted-foreground tabular-nums'>
                {dateRange(
                  sprint.data.estimated_start,
                  sprint.data.estimated_finish
                )}
                {sprint.data.closed && t('taskboard.closedSuffix')}
              </p>
            )}
            {stats.data && (
              <dl className='mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm'>
                <Stat
                  label={t('taskboard.stats.pointsDone')}
                  value={t('taskboard.ofTotal', {
                    done: number(pointsDone(stats.data).done, {
                      maximumFractionDigits: 1,
                    }),
                    total: number(pointsDone(stats.data).total, {
                      maximumFractionDigits: 1,
                    }),
                  })}
                />
                <Stat
                  label={t('taskboard.stats.storiesClosed')}
                  value={t('taskboard.ofTotal', {
                    done: number(stats.data.completed_userstories),
                    total: number(stats.data.total_userstories),
                  })}
                />
                <Stat
                  label={t('taskboard.stats.tasksClosed')}
                  value={t('taskboard.ofTotal', {
                    done: number(stats.data.completed_tasks),
                    total: number(stats.data.total_tasks),
                  })}
                />
                <Stat
                  label={t('taskboard.stats.iocaineDoses')}
                  value={number(stats.data.iocaine_doses)}
                />
              </dl>
            )}
          </div>
          {stats.data && <Burndown stats={stats.data} />}
        </div>

        {tasks.isPending || stories.isPending ? (
          <Skeleton className='mt-6 h-64 w-full' />
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCorners}
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
            <div className='-mx-4 mt-6 overflow-x-auto px-4 pb-6'>
              <div
                role='table'
                aria-label={t('common:terms.taskboard')}
                className='grid min-w-max gap-px overflow-hidden rounded-lg border bg-border'
                style={{
                  gridTemplateColumns: `16rem repeat(${statuses.length}, minmax(13rem, 1fr))`,
                }}
              >
                <div role='row' className='contents'>
                  <div
                    role='columnheader'
                    className='sticky top-0 bg-muted px-3 py-2 text-sm font-semibold'
                  >
                    {t('common:terms.story', { count: 1 })}
                  </div>
                  {statuses.map((s) => (
                    <div
                      key={s.id}
                      role='columnheader'
                      className='flex items-center gap-2 bg-muted px-3 py-2 text-sm font-semibold'
                    >
                      <StatusDot color={s.color} />
                      {s.name}
                    </div>
                  ))}
                </div>

                {sprintStories.map((story) => (
                  <Row
                    key={story.id}
                    project={project}
                    sprintId={sprintId}
                    story={story}
                    statuses={statuses}
                    cells={view}
                    byId={byId}
                    editable={editable}
                  />
                ))}
                <Row
                  project={project}
                  sprintId={sprintId}
                  story={null}
                  statuses={statuses}
                  cells={view}
                  byId={byId}
                  editable={editable}
                />
              </div>
            </div>
            <DragOverlay>
              {active && <TaskFace project={project} task={active} lifted />}
            </DragOverlay>
          </DndContext>
        )}
      </Main>
    </>
  )
}

/** Points done ("2 of 13"): total minus what was still open on the latest past day. */
function pointsDone(stats: SprintStats) {
  const total = Object.values(stats.total_points).reduce((a, b) => a + b, 0)
  const today = format(new Date(), 'yyyy-MM-dd')
  const past = stats.days.filter((d) => d.day <= today)
  const open = past[past.length - 1]?.open_points
  const done = open === undefined ? 0 : total - open
  return { done, total }
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className='text-xs text-muted-foreground'>{label}</dt>
      <dd className='font-medium tabular-nums'>{value}</dd>
    </div>
  )
}

function SprintSwitcher({
  project,
  current,
  sprintId,
}: {
  project: Project
  current?: Milestone
  sprintId: Id
}) {
  const { t } = useTranslation(['backlog', 'common'])
  const navigate = useNavigate()
  const open = useMilestones(project.id)
  const [showClosed, setShowClosed] = useState(false)
  const closed = useClosedSprints(project.id, showClosed)
  const go = (id: Id) =>
    navigate({
      to: '/p/$slug/taskboard/$sprint',
      params: { slug: project.slug, sprint: String(id) },
    })

  return (
    <DropdownMenu onOpenChange={(o) => o && setShowClosed(true)}>
      <DropdownMenuTrigger className='-mx-1 inline-flex items-center gap-1.5 rounded-md px-1 text-2xl font-semibold tracking-tight outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring'>
        <h1>{current?.name ?? t('common:terms.sprint', { count: 1 })}</h1>
        <ChevronDown className='size-5 text-muted-foreground' />
      </DropdownMenuTrigger>
      <DropdownMenuContent align='start' className='max-h-96 min-w-56'>
        <DropdownMenuLabel className='text-xs font-normal text-muted-foreground'>
          {t('sprint.openSprints')}
        </DropdownMenuLabel>
        {(open.data ?? []).map((s) => (
          <DropdownMenuItem key={s.id} onSelect={() => go(s.id)}>
            {s.name}
            {s.id === sprintId && <Check className='ms-auto' />}
          </DropdownMenuItem>
        ))}
        {(closed.data ?? []).length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className='text-xs font-normal text-muted-foreground'>
              {t('sprint.closedSprints')}
            </DropdownMenuLabel>
            {closed.data!.map((s) => (
              <DropdownMenuItem key={s.id} onSelect={() => go(s.id)}>
                {s.name}
                {s.id === sprintId && <Check className='ms-auto' />}
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Row({
  project,
  sprintId,
  story,
  statuses,
  cells,
  byId,
  editable,
}: {
  project: Project
  sprintId: Id
  story: UserStory | null
  statuses: Project['task_statuses']
  cells: Cells
  byId: Map<Id, Task>
  editable: boolean
}) {
  const { t } = useTranslation(['backlog', 'common'])
  const { open } = useRefParam()
  const canAddTask = can(project, 'add_task')
  const all = statuses.flatMap(
    (s) => cells[cellKey(story?.id ?? null, s.id)] ?? []
  )
  const done = all.filter((id) => byId.get(id)?.is_closed).length

  return (
    <div role='row' className='contents'>
      <div
        role='rowheader'
        className='grid content-start gap-1.5 bg-card p-3 text-sm'
      >
        {story ? (
          <>
            <button
              onClick={() => open(story.ref)}
              className={cn(
                'text-start leading-snug hover:underline hover:underline-offset-4',
                story.is_closed && 'text-muted-foreground line-through'
              )}
            >
              <span className='me-1.5 text-xs text-muted-foreground tabular-nums'>
                #{story.ref}
              </span>
              {story.subject}
            </button>
            <span className='flex items-center gap-2 text-xs text-muted-foreground'>
              <StatusDot color={story.status_extra_info.color} />
              {story.status_extra_info.name}
              <span className='ms-auto tabular-nums'>
                <Points value={story.total_points} />{' '}
                {t('taskboard.pointsUnit')}
              </span>
            </span>
          </>
        ) : (
          <span className='text-muted-foreground'>
            {t('taskboard.noStoryRow')}
          </span>
        )}
        {all.length > 0 && (
          <span className='text-xs text-muted-foreground tabular-nums'>
            {t('taskboard.tasksDone', { done, count: all.length })}
          </span>
        )}
        {canAddTask && (
          <AddTask
            project={project}
            sprintId={sprintId}
            storyId={story?.id ?? null}
          />
        )}
      </div>
      {statuses.map((status) => (
        <Cell
          key={status.id}
          project={project}
          id={cellKey(story?.id ?? null, status.id)}
          label={t('taskboard.cell', {
            row: story ? `#${story.ref}` : t('taskboard.noStory'),
            status: status.name,
          })}
          tasks={(cells[cellKey(story?.id ?? null, status.id)] ?? [])
            .map((id) => byId.get(id))
            .filter((t): t is Task => !!t)}
          editable={editable}
        />
      ))}
    </div>
  )
}

function AddTask({
  project,
  sprintId,
  storyId,
}: {
  project: Project
  sprintId: Id
  storyId: Id | null
}) {
  const { t } = useTranslation(['backlog', 'common'])
  const create = useBulkCreateTasks(project, sprintId)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className='inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground'
      >
        <Plus className='size-3.5' />
        {t('taskboard.addTasks.trigger')}
      </button>
    )
  return (
    <form
      className='grid gap-1.5'
      onSubmit={(e) => {
        e.preventDefault()
        if (!text.trim()) return
        create.mutate(
          { storyId, text: text.trim() },
          {
            onSuccess: () => {
              setText('')
              setOpen(false)
            },
          }
        )
      }}
    >
      <textarea
        autoFocus
        value={text}
        rows={3}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false)
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey))
            e.currentTarget.form?.requestSubmit()
        }}
        aria-label={t('taskboard.addTasks.inputLabel')}
        placeholder={t('taskboard.addTasks.placeholder')}
        className='w-full rounded-md border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring'
      />
      <div className='flex gap-1.5'>
        <Button size='sm' className='h-7' disabled={create.isPending}>
          {t('common:actions.add')}
        </Button>
        <Button
          size='sm'
          variant='ghost'
          className='h-7'
          type='button'
          onClick={() => setOpen(false)}
        >
          {t('common:actions.cancel')}
        </Button>
      </div>
    </form>
  )
}

function Cell({
  project,
  id,
  label,
  tasks,
  editable,
}: {
  project: Project
  id: string
  label: string
  tasks: Task[]
  editable: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `cell:${id}` })
  return (
    <div
      ref={setNodeRef}
      role='cell'
      aria-label={label}
      className={cn('min-h-20 bg-card p-2', isOver && 'bg-accent')}
    >
      <SortableContext
        items={tasks.map((t) => t.id)}
        strategy={verticalListSortingStrategy}
      >
        <ul className='grid gap-1.5'>
          {tasks.map((task) => (
            <TaskCard
              key={task.id}
              project={project}
              task={task}
              draggable={editable}
            />
          ))}
        </ul>
      </SortableContext>
    </div>
  )
}

function TaskCard({
  project,
  task,
  draggable,
}: {
  project: Project
  task: Task
  draggable: boolean
}) {
  const { t } = useTranslation(['backlog', 'common'])
  const { open } = useRefParam()
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id, disabled: !draggable })
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(isDragging && 'opacity-40')}
    >
      <TaskFace
        project={project}
        task={task}
        {...attributes}
        {...listeners}
        aria-roledescription={
          draggable ? t('taskboard.task.draggable') : undefined
        }
        onClick={() => open(task.ref)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') open(task.ref)
          else listeners?.onKeyDown?.(e)
        }}
      />
    </li>
  )
}

function TaskFace({
  project,
  task,
  lifted,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  project: Project
  task: Task
  lifted?: boolean
}) {
  const { t } = useTranslation(['backlog', 'common'])
  const assignee = project.members.find((m) => m.id === task.assigned_to)
  return (
    <div
      role='button'
      tabIndex={0}
      className={cn(
        'grid cursor-pointer gap-1.5 rounded-md border bg-background p-2 text-sm shadow-xs outline-none hover:border-foreground/20 focus-visible:ring-2 focus-visible:ring-ring',
        task.is_blocked && 'border-s-4 border-s-destructive',
        task.is_closed && 'text-muted-foreground',
        lifted && 'rotate-1 cursor-grabbing shadow-lg',
        className
      )}
      {...props}
    >
      <p
        className={cn(
          'line-clamp-3 leading-snug',
          task.is_closed && 'line-through'
        )}
      >
        {task.subject}
      </p>
      <div className='flex items-center gap-1.5 text-xs text-muted-foreground'>
        <span className='tabular-nums'>#{task.ref}</span>
        {task.is_blocked && (
          <Ban
            className='size-3 text-destructive'
            aria-label={t('taskboard.task.blocked')}
          />
        )}
        {task.is_iocaine && (
          <Flame
            className='size-3 text-brass'
            aria-label={t('taskboard.task.iocaine')}
          />
        )}
        {assignee && <UserAvatar user={assignee} className='ms-auto size-5' />}
      </div>
    </div>
  )
}
