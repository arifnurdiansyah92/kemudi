import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useFormat } from '@/i18n/format'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import { useMilestones } from '@/lib/taiga/queries'
import { useUpdateSprint } from '@/lib/taiga/sprints'
import type { Milestone, Project } from '@/lib/taiga/types'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ConfirmDialog } from '@/components/confirm-dialog'

type Destination = 'next' | 'backlog' | 'stay'

/**
 * Closing a sprint is the delivery checkpoint: show what got done, and
 * decide where the unfinished stories go instead of leaving them behind
 * in a closed sprint.
 */
export function CloseSprintDialog({
  project,
  sprint,
  open,
  onOpenChange,
}: {
  project: Project
  sprint: Milestone
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation(['backlog', 'common'])
  const format = useFormat()
  const close = useUpdateSprint(sprint.id)
  const sprints = useMilestones(project.id)
  const next = (sprints.data ?? [])
    .filter((s) => s.id !== sprint.id && !s.closed)
    .sort((a, b) => a.estimated_start.localeCompare(b.estimated_start))[0]

  const stories = sprint.user_stories ?? []
  const open_ = stories.filter((s) => !s.is_closed)
  // No choice yet: default to the next sprint once the list has loaded.
  const [dest, setDest] = useState<Destination | null>(null)
  const chosen = dest ?? (next ? 'next' : 'backlog')
  const target: Destination = chosen === 'next' && !next ? 'backlog' : chosen

  const move = useMutation({
    mutationFn: async () => {
      if (open_.length === 0 || target === 'stay') return
      if (target === 'next' && next) {
        await api.post('/userstories/bulk_update_milestone', {
          project_id: project.id,
          milestone_id: next.id,
          bulk_stories: open_.map((s, i) => ({ us_id: s.id, order: i })),
        })
        return
      }
      for (const s of open_)
        await api.patch(`/userstories/${s.id}`, {
          milestone: null,
          version: s.version,
        })
    },
    onError: onFail,
  })

  const busy = move.isPending || close.isPending

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('sprint.close.title', { name: sprint.name })}
      desc={t('sprint.close.summary', {
        done: format.number(stories.length - open_.length),
        total: format.number(stories.length),
        points: format.number(sprint.closed_points ?? 0),
        totalPoints: format.number(sprint.total_points ?? 0),
      })}
      confirmText={t('sprint.close.confirm')}
      isLoading={busy}
      handleConfirm={async () => {
        await move.mutateAsync()
        close.mutate({ closed: true }, { onSuccess: () => onOpenChange(false) })
      }}
    >
      {open_.length > 0 && (
        <fieldset className='grid gap-3'>
          <legend className='mb-2 text-sm font-medium'>
            {t('sprint.close.openStories', { count: open_.length })}
          </legend>
          <ul className='max-h-32 overflow-y-auto rounded-md border text-sm'>
            {open_.map((s) => (
              <li
                key={s.id}
                className='flex gap-2 border-b px-3 py-1.5 last:border-b-0'
              >
                <span className='text-muted-foreground tabular-nums'>
                  #{s.ref}
                </span>
                <span className='min-w-0 flex-1 break-words'>{s.subject}</span>
              </li>
            ))}
          </ul>
          <RadioGroup
            value={target}
            onValueChange={(v) => setDest(v as Destination)}
            className='gap-2'
          >
            {next && (
              <Label className='flex items-center gap-2 font-normal'>
                <RadioGroupItem value='next' />
                {t('sprint.close.toNext', { name: next.name })}
              </Label>
            )}
            <Label className='flex items-center gap-2 font-normal'>
              <RadioGroupItem value='backlog' />
              {t('sprint.close.toBacklog')}
            </Label>
            <Label className='flex items-center gap-2 font-normal'>
              <RadioGroupItem value='stay' />
              {t('sprint.close.stay')}
            </Label>
          </RadioGroup>
        </fieldset>
      )}
    </ConfirmDialog>
  )
}
