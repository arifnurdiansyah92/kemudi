import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { MoreHorizontal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
import { CloseSprintDialog } from './close-sprint-dialog'

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
  const { t } = useTranslation(['backlog', 'common'])
  const navigate = useNavigate()
  const update = useUpdateSprint(sprint.id)
  const remove = useDeleteSprint()
  const [editing, setEditing] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [closing, setClosing] = useState(false)

  const canEdit = can(project, 'modify_milestone')
  const canDelete = can(project, 'delete_milestone')
  if (!canEdit && !canDelete) return null

  return (
    <>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant='ghost'
            size='icon'
            className={className ?? 'size-8'}
            aria-label={t('sprint.menu.actions', { name: sprint.name })}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' className='min-w-44'>
          {canEdit && (
            <>
              <DropdownMenuItem onSelect={() => setEditing(true)}>
                {t('sprint.menu.edit')}
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() =>
                  sprint.closed
                    ? update.mutate({ closed: false })
                    : setClosing(true)
                }
              >
                {sprint.closed
                  ? t('sprint.menu.reopen')
                  : t('sprint.menu.close')}
              </DropdownMenuItem>
            </>
          )}
          {canDelete && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant='destructive'
                onSelect={() => setDeleting(true)}
              >
                {t('sprint.menu.delete')}
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
      <CloseSprintDialog
        project={project}
        sprint={sprint}
        open={closing}
        onOpenChange={setClosing}
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t('sprint.menu.deleteTitle', { name: sprint.name })}
        desc={t('sprint.menu.deleteDescription')}
        confirmText={t('sprint.menu.delete')}
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
