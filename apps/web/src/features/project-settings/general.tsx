import { useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/stores/auth-store'
import {
  useDeleteProject,
  useProjectLogo,
  useStartTransfer,
  useUpdateProject,
} from '@/lib/taiga/admin'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useProject } from '@/features/project/use-project'
import { DuplicateProjectDialog } from '@/features/projects/duplicate-dialog'
import { SettingsSection } from './layout'

export function GeneralSettings() {
  const project = useProject()
  return (
    <div className='grid gap-6'>
      <Details key={project.modified_date} project={project} />
      <Logo project={project} />
      <Modules project={project} />
      <Copy project={project} />
      {project.i_am_owner && <Transfer project={project} />}
      {project.i_am_owner && <Delete project={project} />}
    </div>
  )
}

function Details({ project }: { project: Project }) {
  const { t } = useTranslation(['admin', 'common'])
  const update = useUpdateProject(project)
  const p = project as Project & {
    total_milestones: number | null
    total_story_points: number | null
  }
  const [form, setForm] = useState({
    name: p.name,
    description: p.description,
    total_milestones: p.total_milestones ?? '',
    total_story_points: p.total_story_points ?? '',
  })
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })

  return (
    <SettingsSection title={t('general.details.title')}>
      <form
        className='grid gap-4'
        onSubmit={(e) => {
          e.preventDefault()
          update.mutate({
            ...form,
            name: form.name.trim(),
            total_milestones:
              form.total_milestones === ''
                ? null
                : Number(form.total_milestones),
            total_story_points:
              form.total_story_points === ''
                ? null
                : Number(form.total_story_points),
          })
        }}
      >
        <div className='grid gap-1.5'>
          <Label htmlFor='p-name'>{t('shared.name')}</Label>
          <Input
            id='p-name'
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='p-desc'>{t('common:terms.description')}</Label>
          <Textarea
            id='p-desc'
            rows={3}
            value={form.description}
            onChange={(e) => set({ description: e.target.value })}
          />
        </div>
        <div className='grid gap-4 sm:grid-cols-2'>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-sprints'>
              {t('general.details.plannedSprints')}
            </Label>
            <Input
              id='p-sprints'
              type='number'
              min={0}
              value={form.total_milestones}
              onChange={(e) => set({ total_milestones: e.target.value })}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-points'>
              {t('general.details.plannedPoints')}
            </Label>
            <Input
              id='p-points'
              type='number'
              min={0}
              value={form.total_story_points}
              onChange={(e) => set({ total_story_points: e.target.value })}
            />
          </div>
        </div>
        <p className='-mt-2 text-xs text-muted-foreground'>
          {t('general.details.burndownHint')}
        </p>
        <div>
          <Button
            type='submit'
            disabled={!form.name.trim() || update.isPending}
          >
            {update.isPending && <Loader2 className='animate-spin' />}
            {t('general.details.save')}
          </Button>
        </div>
      </form>
    </SettingsSection>
  )
}

function Logo({ project }: { project: Project }) {
  const { t } = useTranslation(['admin', 'common'])
  const { change, remove } = useProjectLogo(project)
  const input = useRef<HTMLInputElement>(null)
  const logo = (project as Project & { logo_big_url: string | null })
    .logo_big_url
  return (
    <SettingsSection
      title={t('general.logo.title')}
      description={t('general.logo.description')}
    >
      <div className='flex items-center gap-4'>
        {logo ? (
          <img src={logo} alt='' className='size-16 rounded-lg object-cover' />
        ) : (
          <span className='flex size-16 items-center justify-center rounded-lg bg-primary text-2xl font-semibold text-primary-foreground'>
            {project.name.slice(0, 1).toUpperCase()}
          </span>
        )}
        <input
          ref={input}
          type='file'
          accept='image/*'
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) change.mutate(file)
            e.target.value = ''
          }}
        />
        <Button
          variant='outline'
          size='sm'
          onClick={() => input.current?.click()}
          disabled={change.isPending}
        >
          {change.isPending && <Loader2 className='animate-spin' />}
          {t('general.logo.upload')}
        </Button>
        {logo && (
          <Button variant='ghost' size='sm' onClick={() => remove.mutate()}>
            {t('general.logo.remove')}
          </Button>
        )}
      </div>
    </SettingsSection>
  )
}

/** Project flag and its label key under general.modules. */
const MODULES = [
  ['is_epics_activated', 'epics'],
  ['is_backlog_activated', 'scrum'],
  ['is_kanban_activated', 'kanban'],
  ['is_issues_activated', 'issues'],
  ['is_wiki_activated', 'wiki'],
] as const

/** Meeting services by brand name; brand names are not translated. */
const MEETING_SERVICES = [
  ['whereby-com', 'Whereby'],
  ['jitsi', 'Jitsi'],
  ['talky', 'Talky'],
] as const

function Modules({ project }: { project: Project }) {
  const { t } = useTranslation(['admin', 'common'])
  const update = useUpdateProject(project)
  const [call, setCall] = useState(project.videoconferences ?? '')
  const [room, setRoom] = useState(project.videoconferences_extra_data ?? '')
  return (
    <SettingsSection
      title={t('general.modules.title')}
      description={t('general.modules.description')}
    >
      <div className='grid gap-3'>
        {MODULES.map(([key, name]) => (
          <label
            key={key}
            className='flex items-center justify-between gap-4 text-sm'
          >
            <span>
              <span className='font-medium'>
                {t(`general.modules.${name}`)}
              </span>
              <span className='block text-muted-foreground'>
                {t(`general.modules.${name}Hint`)}
              </span>
            </span>
            <Switch
              checked={!!project[key]}
              onCheckedChange={(v) => update.mutate({ [key]: v })}
            />
          </label>
        ))}
        <div className='mt-2 grid gap-2 border-t pt-4 sm:grid-cols-[12rem_1fr_auto] sm:items-end'>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-call'>
              {t('general.modules.meetingService')}
            </Label>
            <select
              id='p-call'
              value={call}
              onChange={(e) => setCall(e.target.value)}
              className='h-9 rounded-md border bg-transparent px-2 text-sm'
            >
              <option value=''>{t('common:status.none')}</option>
              {MEETING_SERVICES.map(([value, name]) => (
                <option key={value} value={value}>
                  {name}
                </option>
              ))}
              <option value='custom'>{t('general.modules.customLink')}</option>
            </select>
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-room'>
              {call === 'custom'
                ? t('general.modules.meetingLink')
                : t('general.modules.roomName')}
            </Label>
            <Input
              id='p-room'
              value={room}
              onChange={(e) => setRoom(e.target.value)}
              disabled={!call}
            />
          </div>
          <Button
            variant='outline'
            onClick={() =>
              update.mutate({
                videoconferences: call || null,
                videoconferences_extra_data: room,
              })
            }
          >
            {t('general.modules.saveMeeting')}
          </Button>
        </div>
      </div>
    </SettingsSection>
  )
}

function Copy({ project }: { project: Project }) {
  const { t } = useTranslation(['admin', 'common'])
  const [open, setOpen] = useState(false)
  return (
    <SettingsSection
      title={t('general.duplicate.title')}
      description={t('general.duplicate.description')}
    >
      <Button variant='outline' onClick={() => setOpen(true)}>
        {t('general.duplicate.action')}
      </Button>
      {open && (
        <DuplicateProjectDialog
          project={project}
          open={open}
          onOpenChange={setOpen}
        />
      )}
    </SettingsSection>
  )
}

function Transfer({ project }: { project: Project }) {
  const { t } = useTranslation(['admin', 'common'])
  const me = useAuthStore((s) => s.session?.user.id)
  const start = useStartTransfer(project)
  const [user, setUser] = useState<number | ''>('')
  const [reason, setReason] = useState('')
  const others = project.members.filter((m) => m.is_active && m.id !== me)
  return (
    <SettingsSection
      title={t('general.transfer.title')}
      description={t('general.transfer.description')}
    >
      {others.length === 0 ? (
        <p className='text-sm text-muted-foreground'>
          {t('general.transfer.inviteFirst')}
        </p>
      ) : (
        <form
          className='grid gap-3 sm:grid-cols-[14rem_1fr_auto] sm:items-end'
          onSubmit={(e) => {
            e.preventDefault()
            if (user) start.mutate({ user, reason })
          }}
        >
          <div className='grid gap-1.5'>
            <Label htmlFor='t-user'>{t('general.transfer.newOwner')}</Label>
            <select
              id='t-user'
              value={user}
              onChange={(e) =>
                setUser(e.target.value ? Number(e.target.value) : '')
              }
              className='h-9 rounded-md border bg-transparent px-2 text-sm'
            >
              <option value=''>{t('general.transfer.chooseMember')}</option>
              {others.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.full_name_display}
                </option>
              ))}
            </select>
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='t-reason'>{t('general.transfer.message')}</Label>
            <Input
              id='t-reason'
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <Button
            type='submit'
            variant='outline'
            disabled={!user || start.isPending}
          >
            {t('general.transfer.offer')}
          </Button>
        </form>
      )}
    </SettingsSection>
  )
}

function Delete({ project }: { project: Project }) {
  const { t } = useTranslation(['admin', 'common'])
  const navigate = useNavigate()
  const remove = useDeleteProject(project)
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  return (
    <SettingsSection
      danger
      title={t('general.delete.title')}
      description={t('general.delete.description')}
    >
      <Button variant='destructive' onClick={() => setOpen(true)}>
        {t('general.delete.action', { name: project.name })}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t('general.delete.confirmTitle', { name: project.name })}
        desc={
          <span className='grid gap-3'>
            <span>{t('general.delete.typeName')}</span>
            <Input
              aria-label={t('general.delete.nameLabel')}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </span>
        }
        confirmText={t('general.delete.title')}
        destructive
        disabled={typed !== project.name}
        isLoading={remove.isPending}
        handleConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => navigate({ to: '/projects' }),
          })
        }
      />
    </SettingsSection>
  )
}
