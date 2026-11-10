import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { MoreHorizontal } from 'lucide-react'
import { useDeleteSprint, useUpdateSprint } from '@/lib/taiga/sprints'
import type { Milestone, Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EditSprintDialog } from '@/features/backlog/new-sprint-dialog'
import { can } from '@/features/project/use-project'

/** Edit, close or reopen, and delete a sprint. */
export function SprintMenu({
  project,
  sprint,
  className,
}: {
  project: Project
  sprint: Milestone
  className?: string
}) {
  const navigate = useNavigate()
  const update = useUpdateSprint(sprint.id)
  const remove = useDeleteSprint()
  const [editing, setEditing] = useState(false)
  const [deleting, setDeleting] = useState(false)

  if (!can(project, 'modify_milestone') && !can(project, 'delete_milestone'))
    return null

  return (
    <>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant='ghost'
            size='icon'
            className={className ?? 'size-8'}
            aria-label={`Actions for ${sprint.name}`}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' className='min-w-44'>
          {can(project, 'modify_milestone') && (
            <>
              <DropdownMenuItem onSelect={() => setEditing(true)}>
                Edit sprint
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => update.mutate({ closed: !sprint.closed })}
              >
                {sprint.closed ? 'Reopen sprint' : 'Close sprint'}
              </DropdownMenuItem>
            </>
          )}
          {can(project, 'delete_milestone') && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant='destructive'
                onSelect={() => setDeleting(true)}
              >
                Delete sprint
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <EditSprintDialog
        sprint={sprint}
        open={editing}
        onOpenChange={setEditing}
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${sprint.name}?`}
        desc='Its stories go back to the backlog. Its tasks stay with their stories. This cannot be undone.'
        confirmText='Delete sprint'
        destructive
        isLoading={remove.isPending}
        handleConfirm={() =>
          remove.mutate(sprint, {
            onSuccess: () => {
              setDeleting(false)
              navigate({
                to: '/p/$slug/backlog',
                params: { slug: project.slug },
              })
            },
          })
        }
      />
    </>
  )
}
