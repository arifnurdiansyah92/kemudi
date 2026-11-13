import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
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
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { ProjectSummary } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'

/** Your projects, in your own order (drag the handle to rearrange). */
export function ProjectList({ projects }: { projects: ProjectSummary[] }) {
  const qc = useQueryClient()
  const [local, setLocal] = useState<ProjectSummary[] | null>(null)
  const list = local ?? projects
  const save = useMutation({
    mutationFn: (ordered: ProjectSummary[]) =>
      api.post(
        '/projects/bulk_update_order',
        ordered.map((p, i) => ({ project_id: p.id, order: i + 1 }))
      ),
    onError: onFail,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['projects'] }).then(() =>
        setLocal(null)
      )
    },
  })
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const from = list.findIndex((p) => p.id === active.id)
    const to = list.findIndex((p) => p.id === over.id)
    const next = arrayMove(list, from, to)
    setLocal(next)
    save.mutate(next)
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      modifiers={[restrictToVerticalAxis]}
      onDragEnd={onDragEnd}
    >
      <SortableContext
        items={list.map((p) => p.id)}
        strategy={verticalListSortingStrategy}
      >
        <ul className='divide-y rounded-lg border bg-card'>
          {list.map((project) => (
            <Row
              key={project.id}
              project={project}
              draggable={list.length > 1}
            />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  )
}

function Row({
  project,
  draggable,
}: {
  project: ProjectSummary
  draggable: boolean
}) {
  const { t } = useTranslation('home')
  const format = useFormat()
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: project.id, disabled: !draggable })
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        'group relative flex items-start bg-card',
        isDragging && 'z-10 shadow-lg'
      )}
    >
      {draggable && (
        <button
          ref={setActivatorNodeRef}
          {...attributes}
          {...listeners}
          aria-label={t('projects.list.move', { name: project.name })}
          className='ms-2 mt-5 cursor-grab rounded p-0.5 text-muted-foreground/40 outline-none group-hover:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring active:cursor-grabbing'
        >
          <GripVertical className='size-4' />
        </button>
      )}
      <Link
        to='/p/$slug'
        params={{ slug: project.slug }}
        className='flex min-w-0 flex-1 items-start gap-4 px-4 py-4 transition-colors outline-none hover:bg-accent/60 focus-visible:bg-accent'
      >
        <span
          aria-hidden='true'
          className='mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-sm font-semibold text-primary-foreground'
        >
          {project.name.slice(0, 1).toUpperCase()}
        </span>
        <span className='min-w-0 flex-1'>
          <span className='flex items-center gap-1.5 font-medium'>
            {project.name}
            {project.is_private && (
              <Badge
                variant='outline'
                className='px-1.5 py-0 text-[0.625rem] font-medium text-muted-foreground'
              >
                {t('projects.list.private')}
              </Badge>
            )}
          </span>
          {project.description && (
            <span className='mt-0.5 line-clamp-1 block text-sm text-muted-foreground'>
              {project.description}
            </span>
          )}
        </span>
        <span className='shrink-0 pt-0.5 text-xs text-muted-foreground tabular-nums max-sm:hidden'>
          {t('projects.list.updated', {
            time: format.timeAgo(project.modified_date),
          })}
        </span>
      </Link>
    </li>
  )
}
