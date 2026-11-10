import { useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
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
  const update = useUpdateProject(project)
  const p = project as Project & {
    is_looking_for_people: boolean
    looking_for_people_note: string
    is_contact_activated: boolean
    total_milestones: number | null
    total_story_points: number | null
  }
  const [form, setForm] = useState({
    name: p.name,
    description: p.description,
    is_private: p.is_private,
    is_looking_for_people: p.is_looking_for_people,
    is_contact_activated: p.is_contact_activated,
    looking_for_people_note: p.looking_for_people_note ?? '',
    total_milestones: p.total_milestones ?? '',
    total_story_points: p.total_story_points ?? '',
  })
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })

  return (
    <SettingsSection title='Details'>
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
          <Label htmlFor='p-name'>Name</Label>
          <Input
            id='p-name'
            value={form.name}
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='p-desc'>Description</Label>
          <Textarea
            id='p-desc'
            rows={3}
            value={form.description}
            onChange={(e) => set({ description: e.target.value })}
          />
        </div>
        <div className='grid gap-4 sm:grid-cols-2'>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-sprints'>Planned sprints</Label>
            <Input
              id='p-sprints'
              type='number'
              min={0}
              value={form.total_milestones}
              onChange={(e) => set({ total_milestones: e.target.value })}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-points'>Planned story points</Label>
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
          Both feed the project burndown in the backlog.
        </p>
        <label className='flex items-center justify-between gap-4 text-sm'>
          <span>
            <span className='font-medium'>Private project</span>
            <span className='block text-muted-foreground'>
              Off makes it public: anyone can view it and find it in Discover.
            </span>
          </span>
          <Switch
            checked={form.is_private}
            onCheckedChange={(v) => set({ is_private: v })}
          />
        </label>
        <label className='flex items-center justify-between gap-4 text-sm'>
          <span>
            <span className='font-medium'>Looking for people</span>
            <span className='block text-muted-foreground'>
              Shows in Discover that the project wants contributors.
            </span>
          </span>
          <Switch
            checked={form.is_looking_for_people}
            onCheckedChange={(v) => set({ is_looking_for_people: v })}
          />
        </label>
        <label className='flex items-center justify-between gap-4 text-sm'>
          <span>
            <span className='font-medium'>Can be contacted</span>
            <span className='block text-muted-foreground'>
              People outside the project can send the admins a message from
              Discover.
            </span>
          </span>
          <Switch
            checked={form.is_contact_activated}
            onCheckedChange={(v) => set({ is_contact_activated: v })}
          />
        </label>
        {form.is_looking_for_people && (
          <Input
            aria-label='Who you are looking for'
            placeholder='Who you are looking for'
            value={form.looking_for_people_note}
            onChange={(e) => set({ looking_for_people_note: e.target.value })}
          />
        )}
        <div>
          <Button
            type='submit'
            disabled={!form.name.trim() || update.isPending}
          >
            {update.isPending && <Loader2 className='animate-spin' />}
            Save details
          </Button>
        </div>
      </form>
    </SettingsSection>
  )
}

function Logo({ project }: { project: Project }) {
  const { change, remove } = useProjectLogo(project)
  const input = useRef<HTMLInputElement>(null)
  const logo = (project as Project & { logo_big_url: string | null })
    .logo_big_url
  return (
    <SettingsSection
      title='Logo'
      description='Square images work best. PNG, JPEG or GIF.'
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
          Upload logo
        </Button>
        {logo && (
          <Button variant='ghost' size='sm' onClick={() => remove.mutate()}>
            Remove
          </Button>
        )}
      </div>
    </SettingsSection>
  )
}

const MODULES = [
  ['is_epics_activated', 'Epics', 'Group stories into larger pieces of work.'],
  ['is_backlog_activated', 'Scrum', 'Backlog, sprints and the taskboard.'],
  ['is_kanban_activated', 'Kanban', 'A board of stories by status.'],
  ['is_issues_activated', 'Issues', 'Bugs, questions and improvements.'],
  ['is_wiki_activated', 'Wiki', 'Pages for the team’s shared knowledge.'],
] as const

function Modules({ project }: { project: Project }) {
  const update = useUpdateProject(project)
  const [call, setCall] = useState(project.videoconferences ?? '')
  const [room, setRoom] = useState(project.videoconferences_extra_data ?? '')
  return (
    <SettingsSection
      title='Modules'
      description='Turn parts of Kemudi on or off for this project.'
    >
      <div className='grid gap-3'>
        {MODULES.map(([key, label, hint]) => (
          <label
            key={key}
            className='flex items-center justify-between gap-4 text-sm'
          >
            <span>
              <span className='font-medium'>{label}</span>
              <span className='block text-muted-foreground'>{hint}</span>
            </span>
            <Switch
              checked={!!project[key]}
              onCheckedChange={(v) => update.mutate({ [key]: v })}
            />
          </label>
        ))}
        <div className='mt-2 grid gap-2 border-t pt-4 sm:grid-cols-[12rem_1fr_auto] sm:items-end'>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-call'>Meeting service</Label>
            <select
              id='p-call'
              value={call}
              onChange={(e) => setCall(e.target.value)}
              className='h-9 rounded-md border bg-transparent px-2 text-sm'
            >
              <option value=''>None</option>
              <option value='whereby-com'>Whereby</option>
              <option value='jitsi'>Jitsi</option>
              <option value='talky'>Talky</option>
              <option value='custom'>Custom link</option>
            </select>
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='p-room'>
              {call === 'custom' ? 'Meeting link' : 'Room name'}
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
            Save meeting
          </Button>
        </div>
      </div>
    </SettingsSection>
  )
}

function Copy({ project }: { project: Project }) {
  const [open, setOpen] = useState(false)
  return (
    <SettingsSection
      title='Duplicate'
      description='Start a new project with this one’s settings, statuses, roles and custom fields.'
    >
      <Button variant='outline' onClick={() => setOpen(true)}>
        Duplicate project
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
  const me = useAuthStore((s) => s.session?.user.id)
  const start = useStartTransfer(project)
  const [user, setUser] = useState<number | ''>('')
  const [reason, setReason] = useState('')
  const others = project.members.filter((m) => m.is_active && m.id !== me)
  return (
    <SettingsSection
      title='Transfer ownership'
      description='The new owner gets an email and must accept. Until then you stay the owner.'
    >
      {others.length === 0 ? (
        <p className='text-sm text-muted-foreground'>Invite a member first.</p>
      ) : (
        <form
          className='grid gap-3 sm:grid-cols-[14rem_1fr_auto] sm:items-end'
          onSubmit={(e) => {
            e.preventDefault()
            if (user) start.mutate({ user, reason })
          }}
        >
          <div className='grid gap-1.5'>
            <Label htmlFor='t-user'>New owner</Label>
            <select
              id='t-user'
              value={user}
              onChange={(e) =>
                setUser(e.target.value ? Number(e.target.value) : '')
              }
              className='h-9 rounded-md border bg-transparent px-2 text-sm'
            >
              <option value=''>Choose a member</option>
              {others.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.full_name_display}
                </option>
              ))}
            </select>
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='t-reason'>Message</Label>
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
            Offer ownership
          </Button>
        </form>
      )}
    </SettingsSection>
  )
}

function Delete({ project }: { project: Project }) {
  const navigate = useNavigate()
  const remove = useDeleteProject(project)
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  return (
    <SettingsSection
      danger
      title='Delete project'
      description='Deletes every story, task, issue, epic, wiki page and attachment in it. This cannot be undone.'
    >
      <Button variant='destructive' onClick={() => setOpen(true)}>
        Delete {project.name}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete ${project.name}?`}
        desc={
          <span className='grid gap-3'>
            <span>Type the project name to confirm.</span>
            <Input
              aria-label='Project name'
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </span>
        }
        confirmText='Delete project'
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
