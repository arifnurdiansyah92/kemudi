import { useState } from 'react'
import { ChevronRight, Loader2, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useCreateEpic,
  useEpicStories,
  useEpics,
  type Epic,
} from '@/lib/taiga/epics'
import type { Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { UserAvatar } from '@/components/user-avatar'
import { can, useProject, useRefParam } from '@/features/project/use-project'
import { StatusDot } from '@/features/story/parts'

const PALETTE = [
  '#3E7BC4',
  '#2E9C8A',
  '#C8933A',
  '#B4466B',
  '#7A5BC2',
  '#5E7A2E',
]

export function Epics() {
  const { t } = useTranslation(['board', 'common'])
  const project = useProject()
  const epics = useEpics(project.id)
  const { open } = useRefParam()
  const [creating, setCreating] = useState(false)
  const list = epics.data ?? []
  const canAdd = can(project, 'add_epic')

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: t('common:terms.epic', { count: 2 }) },
        ]}
      />
      <Main width='list'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-tight'>
              {t('common:terms.epic', { count: 2 })}
            </h1>
            <p className='mt-1 text-sm text-muted-foreground'>
              {t('epics.intro')}
            </p>
          </div>
          {canAdd && (
            <Button size='sm' onClick={() => setCreating(true)}>
              <Plus />
              {t('epics.new')}
            </Button>
          )}
        </div>

        <div className='mt-8'>
          {epics.isPending ? (
            <Skeleton className='h-32 w-full' />
          ) : list.length === 0 ? (
            <div className='rounded-lg border border-dashed p-10 text-center'>
              <p className='font-medium'>{t('epics.empty.title')}</p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('epics.empty.body')}
              </p>
            </div>
          ) : (
            <ul className='divide-y rounded-lg border bg-card'>
              {list.map((epic) => (
                <EpicRow
                  key={epic.id}
                  project={project}
                  epic={epic}
                  onOpen={open}
                />
              ))}
            </ul>
          )}
        </div>
      </Main>
      {creating && (
        <NewEpicDialog
          project={project}
          open={creating}
          onOpenChange={setCreating}
          onCreated={open}
        />
      )}
    </>
  )
}

function EpicRow({
  project,
  epic,
  onOpen,
}: {
  project: Project
  epic: Epic
  onOpen: (ref: number) => void
}) {
  const { t } = useTranslation(['board', 'common'])
  const [expanded, setExpanded] = useState(false)
  const stories = useEpicStories(project.id, epic.id, expanded)
  const { total, progress } = epic.user_stories_counts
  const pct = total ? Math.round((progress / total) * 100) : 0
  const assignee = project.members.find((m) => m.id === epic.assigned_to)

  return (
    <li>
      <div className='flex items-center gap-3 px-3 py-3'>
        <button
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          aria-label={t(expanded ? 'epics.hideStories' : 'epics.showStories', {
            ref: epic.ref,
          })}
          className='rounded p-1 text-muted-foreground hover:bg-accent'
          disabled={total === 0}
        >
          <ChevronRight
            className={cn(
              'size-4 transition-transform',
              expanded && 'rotate-90'
            )}
          />
        </button>
        <span
          aria-hidden='true'
          className='h-8 w-1 shrink-0 rounded-full'
          style={{ backgroundColor: epic.color }}
        />
        <button
          onClick={() => onOpen(epic.ref)}
          className={cn(
            'min-w-0 flex-1 truncate text-start text-sm hover:underline hover:underline-offset-4',
            epic.is_closed && 'text-muted-foreground line-through'
          )}
        >
          <span className='me-2 text-xs text-muted-foreground tabular-nums'>
            #{epic.ref}
          </span>
          {epic.subject}
        </button>
        <span className='hidden w-40 items-center gap-2 sm:flex'>
          <span
            className='h-1.5 flex-1 overflow-hidden rounded-full bg-muted'
            role='progressbar'
            aria-label={t('epics.progress', { ref: epic.ref })}
            aria-valuenow={pct}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span
              className='block h-full bg-success'
              style={{ width: `${pct}%` }}
            />
          </span>
          <span className='w-12 text-end text-xs text-muted-foreground tabular-nums'>
            {progress}/{total}
          </span>
        </span>
        <span className='hidden items-center gap-1.5 text-xs md:inline-flex'>
          <StatusDot color={epic.status_extra_info.color} />
          {epic.status_extra_info.name}
        </span>
        {assignee && <UserAvatar user={assignee} />}
      </div>
      {expanded && (
        <ul className='border-t bg-muted/30 py-1 ps-14'>
          {stories.isPending ? (
            <li className='p-2'>
              <Skeleton className='h-6 w-1/2' />
            </li>
          ) : (
            (stories.data ?? []).map((s) => (
              <li
                key={s.id}
                className='flex items-center gap-3 py-1.5 pe-3 text-sm'
              >
                <span className='w-10 text-xs text-muted-foreground tabular-nums'>
                  #{s.ref}
                </span>
                <button
                  onClick={() => onOpen(s.ref)}
                  className={cn(
                    'min-w-0 flex-1 truncate text-start hover:underline hover:underline-offset-4',
                    s.is_closed && 'text-muted-foreground line-through'
                  )}
                >
                  {s.subject}
                </button>
                <span className='inline-flex items-center gap-1.5 text-xs text-muted-foreground'>
                  <StatusDot color={s.status_extra_info.color} />
                  {s.status_extra_info.name}
                </span>
              </li>
            ))
          )}
        </ul>
      )}
    </li>
  )
}

function NewEpicDialog({
  project,
  open,
  onOpenChange,
  onCreated,
}: {
  project: Project
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (ref: number) => void
}) {
  const { t } = useTranslation(['board', 'common'])
  const create = useCreateEpic(project)
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [color, setColor] = useState(
    () => PALETTE[Math.floor(Math.random() * PALETTE.length)]
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <form
          className='grid gap-4'
          onSubmit={(e) => {
            e.preventDefault()
            if (!subject.trim()) return
            create.mutate(
              { subject: subject.trim(), description, color },
              {
                onSuccess: (epic) => {
                  onOpenChange(false)
                  onCreated(epic.ref)
                },
              }
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>{t('epics.create.title')}</DialogTitle>
            <DialogDescription>
              {t('epics.create.description')}
            </DialogDescription>
          </DialogHeader>
          <div className='grid gap-1.5'>
            <Label htmlFor='epic-subject'>{t('epics.create.name')}</Label>
            <Input
              id='epic-subject'
              autoFocus
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
            />
          </div>
          <fieldset className='grid gap-1.5'>
            <legend className='mb-1.5 text-sm font-medium'>
              {t('epics.create.colour')}
            </legend>
            <div className='flex items-center gap-2'>
              {PALETTE.map((c) => (
                <button
                  key={c}
                  type='button'
                  aria-label={c}
                  aria-pressed={color === c}
                  onClick={() => setColor(c)}
                  className={cn(
                    'size-7 rounded-full ring-offset-2 ring-offset-background',
                    color === c && 'ring-2 ring-ring'
                  )}
                  style={{ backgroundColor: c }}
                />
              ))}
              <input
                type='color'
                aria-label={t('epics.create.otherColour')}
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className='size-7 cursor-pointer rounded-full border bg-transparent'
              />
            </div>
          </fieldset>
          <div className='grid gap-1.5'>
            <Label htmlFor='epic-description'>
              {t('common:terms.description')}
            </Label>
            <Textarea
              id='epic-description'
              rows={4}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('epics.create.descriptionPlaceholder')}
            />
          </div>
          <DialogFooter>
            <Button
              type='submit'
              disabled={!subject.trim() || create.isPending}
            >
              {create.isPending && <Loader2 className='animate-spin' />}
              {t('epics.create.submit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
