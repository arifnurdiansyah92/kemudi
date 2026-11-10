import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCreateTask, useTasks, useUpdateTask } from '@/lib/taiga/queries'
import type { Item, Project, Task } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { UserAvatar } from '@/components/user-avatar'
import { can, useRefParam } from '@/features/project/use-project'

/** A story's tasks as a checklist; each task opens in the sheet. */
export function StoryTasks({
  project,
  story,
}: {
  project: Project
  story: Item
}) {
  const { t } = useTranslation('item')
  const tasks = useTasks(story.id)
  const create = useCreateTask(project)
  const update = useUpdateTask(project)
  const { open } = useRefParam()
  const [subject, setSubject] = useState('')
  const canEdit = can(project, 'modify_task')

  const closedStatus = project.task_statuses.find((s) => s.is_closed)
  const openStatus =
    project.task_statuses.find((s) => s.id === project.default_task_status) ??
    project.task_statuses.find((s) => !s.is_closed)

  const toggle = (task: Task, done: boolean) => {
    const status = done ? closedStatus : openStatus
    if (status) update.mutate({ task, patch: { status: status.id } })
  }

  if (tasks.isPending) return <Skeleton className='h-16 w-full' />
  const list = tasks.data ?? []
  const done = list.filter((task) => task.is_closed).length

  return (
    <div className='grid gap-1'>
      {list.length > 0 && (
        <p className='mb-1 text-xs text-muted-foreground tabular-nums'>
          {t('tasks.progress', { done, total: list.length })}
        </p>
      )}
      <ul className='grid gap-0.5'>
        {list.map((task) => {
          const assignee = project.members.find(
            (m) => m.id === task.assigned_to
          )
          return (
            <li
              key={task.id}
              className='flex items-center gap-3 rounded-md px-1 py-1.5 text-sm hover:bg-accent/50'
            >
              <Checkbox
                aria-label={
                  task.is_closed
                    ? t('tasks.markNotDone', { ref: task.ref })
                    : t('tasks.markDone', { ref: task.ref })
                }
                checked={task.is_closed}
                disabled={!canEdit || !closedStatus}
                onCheckedChange={(v) => toggle(task, v === true)}
              />
              <span className='w-9 shrink-0 text-xs text-muted-foreground tabular-nums'>
                #{task.ref}
              </span>
              <button
                onClick={() => open(task.ref)}
                className={cn(
                  'min-w-0 flex-1 truncate text-start hover:underline hover:underline-offset-4',
                  task.is_closed && 'text-muted-foreground line-through'
                )}
              >
                {task.subject}
              </button>
              {assignee && <UserAvatar user={assignee} className='size-5' />}
              <span className='text-xs text-muted-foreground'>
                {task.status_extra_info.name}
              </span>
            </li>
          )
        })}
      </ul>
      {can(project, 'add_task') && (
        <form
          className='mt-1'
          onSubmit={(e) => {
            e.preventDefault()
            const value = subject.trim()
            if (!value) return
            create.mutate({ story, subject: value })
            setSubject('')
          }}
        >
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder={t('tasks.addPlaceholder')}
            aria-label={t('tasks.new')}
            className='h-9 w-full rounded-md border border-dashed bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-solid focus-visible:ring-2 focus-visible:ring-ring'
          />
        </form>
      )}
    </div>
  )
}
