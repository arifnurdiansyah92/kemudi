import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus } from 'lucide-react'
import { useUpdateProject } from '@/lib/taiga/admin'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Id, Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

interface Role {
  id: Id
  name: string
  order: number
  computable: boolean
  permissions: string[]
  members_count: number
}

type Action = 'view' | 'add' | 'modify' | 'comment' | 'delete'
const ACTIONS: Action[] = ['view', 'add', 'modify', 'comment', 'delete']

/** Permission codes per area and action, as kemudi-back names them. */
const AREAS: { label: string; perms: Partial<Record<Action, string>> }[] = [
  {
    label: 'Epics',
    perms: {
      view: 'view_epics',
      add: 'add_epic',
      modify: 'modify_epic',
      comment: 'comment_epic',
      delete: 'delete_epic',
    },
  },
  {
    label: 'Sprints',
    perms: {
      view: 'view_milestones',
      add: 'add_milestone',
      modify: 'modify_milestone',
      delete: 'delete_milestone',
    },
  },
  {
    label: 'Stories',
    perms: {
      view: 'view_us',
      add: 'add_us',
      modify: 'modify_us',
      comment: 'comment_us',
      delete: 'delete_us',
    },
  },
  {
    label: 'Tasks',
    perms: {
      view: 'view_tasks',
      add: 'add_task',
      modify: 'modify_task',
      comment: 'comment_task',
      delete: 'delete_task',
    },
  },
  {
    label: 'Issues',
    perms: {
      view: 'view_issues',
      add: 'add_issue',
      modify: 'modify_issue',
      comment: 'comment_issue',
      delete: 'delete_issue',
    },
  },
  {
    label: 'Wiki pages',
    perms: {
      view: 'view_wiki_pages',
      add: 'add_wiki_page',
      modify: 'modify_wiki_page',
      comment: 'comment_wiki_page',
      delete: 'delete_wiki_page',
    },
  },
  {
    label: 'Wiki links',
    perms: {
      view: 'view_wiki_links',
      add: 'add_wiki_link',
      modify: 'modify_wiki_link',
      delete: 'delete_wiki_link',
    },
  },
]

function useRoles(project: Project) {
  const qc = useQueryClient()
  const key = ['roles', project.id]
  const settle = () => {
    qc.invalidateQueries({ queryKey: key })
    qc.invalidateQueries({ queryKey: ['project'] })
  }
  const list = useQuery({
    queryKey: key,
    queryFn: async () =>
      (
        await api.get<Role[]>('/roles', { params: { project: project.id } })
      ).data.sort((a, b) => a.order - b.order),
  })
  const update = useMutation({
    mutationFn: ({ role, patch }: { role: Role; patch: Partial<Role> }) =>
      api.patch(`/roles/${role.id}`, patch),
    onError: onFail,
    onSettled: settle,
  })
  const create = useMutation({
    mutationFn: async (name: string) =>
      (
        await api.post<Role>('/roles', {
          project: project.id,
          name,
          computable: false,
          permissions: ['view_project'],
          order: (list.data?.length ?? 0) + 1,
        })
      ).data,
    onError: onFail,
    onSettled: settle,
  })
  const remove = useMutation({
    mutationFn: ({ role, moveTo }: { role: Role; moveTo: Id }) =>
      api.delete(`/roles/${role.id}`, { params: { moveTo } }),
    onError: onFail,
    onSettled: settle,
  })
  return { list, update, create, remove }
}

export function RolesSettings() {
  const project = useProject()
  const roles = useRoles(project)
  const [selected, setSelected] = useState<Id | null>(null)
  const [newName, setNewName] = useState('')
  const list = roles.list.data ?? []
  const role = list.find((r) => r.id === selected) ?? list[0]

  return (
    <div className='grid gap-6'>
      <SettingsSection
        title='Roles'
        description='Every member has one role. Roles that count for points get their own estimate on each story.'
      >
        {roles.list.isPending ? (
          <Skeleton className='h-48 w-full' />
        ) : (
          <div className='grid gap-6 md:grid-cols-[12rem_minmax(0,1fr)]'>
            <div className='grid content-start gap-1'>
              {list.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setSelected(r.id)}
                  className={cn(
                    'flex items-center justify-between rounded-md px-3 py-1.5 text-start text-sm hover:bg-accent',
                    role?.id === r.id && 'bg-accent font-medium'
                  )}
                >
                  {r.name}
                  <span className='text-xs text-muted-foreground tabular-nums'>
                    {r.members_count}
                  </span>
                </button>
              ))}
              <form
                className='mt-2 flex gap-1'
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!newName.trim()) return
                  roles.create.mutate(newName.trim(), {
                    onSuccess: (r) => {
                      setNewName('')
                      setSelected(r.id)
                    },
                  })
                }}
              >
                <Input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder='New role'
                  aria-label='New role name'
                  className='h-8'
                />
                <Button
                  size='icon'
                  variant='outline'
                  className='size-8 shrink-0'
                  aria-label='Add role'
                >
                  <Plus />
                </Button>
              </form>
            </div>
            {role && (
              <RoleEditor
                key={role.id}
                role={role}
                others={list.filter((r) => r.id !== role.id)}
                roles={roles}
              />
            )}
          </div>
        )}
      </SettingsSection>
      {!project.is_private && <PublicPermissions project={project} />}
    </div>
  )
}

function RoleEditor({
  role,
  others,
  roles,
}: {
  role: Role
  others: Role[]
  roles: ReturnType<typeof useRoles>
}) {
  const [name, setName] = useState(role.name)
  const [deleting, setDeleting] = useState(false)
  const [moveTo, setMoveTo] = useState<Id | ''>(others[0]?.id ?? '')
  const has = (p: string) => role.permissions.includes(p)
  const toggle = (p: string, on: boolean) => {
    const next = on
      ? [...new Set([...role.permissions, p])]
      : role.permissions.filter((x) => x !== p)
    roles.update.mutate({ role, patch: { permissions: next } })
  }

  return (
    <div className='grid gap-5'>
      <div className='flex flex-wrap items-end gap-3'>
        <div className='grid flex-1 gap-1.5'>
          <Label htmlFor='role-name'>Name</Label>
          <Input
            id='role-name'
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() =>
              name.trim() &&
              name !== role.name &&
              roles.update.mutate({ role, patch: { name: name.trim() } })
            }
          />
        </div>
        <label className='flex h-9 items-center gap-2 text-sm'>
          <Switch
            checked={role.computable}
            onCheckedChange={(v) =>
              roles.update.mutate({ role, patch: { computable: v } })
            }
          />
          Counts for points
        </label>
      </div>

      <div className='overflow-x-auto'>
        <table className='w-full text-sm'>
          <thead>
            <tr className='text-xs text-muted-foreground'>
              <th scope='col' className='py-2 text-start font-medium'>
                Area
              </th>
              {ACTIONS.map((a) => (
                <th
                  key={a}
                  scope='col'
                  className='px-2 py-2 font-medium capitalize'
                >
                  {a}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className='divide-y'>
            {AREAS.map((area) => (
              <tr key={area.label}>
                <th scope='row' className='py-2 text-start font-medium'>
                  {area.label}
                </th>
                {ACTIONS.map((a) => {
                  const perm = area.perms[a]
                  return (
                    <td key={a} className='px-2 py-2 text-center'>
                      {perm ? (
                        <Checkbox
                          aria-label={`${role.name}: ${a} ${area.label.toLowerCase()}`}
                          checked={has(perm)}
                          onCheckedChange={(v) => toggle(perm, v === true)}
                        />
                      ) : (
                        <span className='text-muted-foreground'>–</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {others.length > 0 && (
        <div>
          <Button variant='outline' size='sm' onClick={() => setDeleting(true)}>
            Delete role
          </Button>
          <ConfirmDialog
            open={deleting}
            onOpenChange={setDeleting}
            title={`Delete the ${role.name} role?`}
            desc={
              <span className='grid gap-2'>
                <span>Members with this role move to:</span>
                <select
                  aria-label='Move members to'
                  value={moveTo}
                  onChange={(e) => setMoveTo(Number(e.target.value))}
                  className='h-9 rounded-md border bg-transparent px-2 text-sm text-foreground'
                >
                  {others.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </span>
            }
            confirmText='Delete role'
            destructive
            disabled={!moveTo}
            isLoading={roles.remove.isPending}
            handleConfirm={() =>
              moveTo &&
              roles.remove.mutate(
                { role, moveTo },
                { onSuccess: () => setDeleting(false) }
              )
            }
          />
        </div>
      )}
      {roles.update.isPending && (
        <p className='flex items-center gap-2 text-xs text-muted-foreground'>
          <Loader2 className='size-3 animate-spin' /> Saving
        </p>
      )}
    </div>
  )
}

/** What signed-in non-members and anonymous visitors may do on a public project. */
function PublicPermissions({ project }: { project: Project }) {
  const update = useUpdateProject(project)
  const p = project as Project & {
    public_permissions: string[]
    anon_permissions: string[]
  }
  const groups = [
    [
      'public_permissions',
      'Signed-in people who are not members',
      p.public_permissions ?? [],
    ],
    [
      'anon_permissions',
      'Visitors who are not signed in',
      p.anon_permissions ?? [],
    ],
  ] as const
  return (
    <SettingsSection
      title='Outside the team'
      description='This project is public. Choose what people outside it can see and do.'
    >
      <div className='grid gap-6'>
        {groups.map(([key, label, perms]) => (
          <fieldset key={key}>
            <legend className='mb-2 text-sm font-medium'>{label}</legend>
            <div className='flex flex-wrap gap-x-5 gap-y-2'>
              {AREAS.map((area) => {
                const view = area.perms.view!
                return (
                  <label key={view} className='flex items-center gap-2 text-sm'>
                    <Checkbox
                      checked={perms.includes(view)}
                      onCheckedChange={(v) =>
                        update.mutate({
                          [key]: v
                            ? [...new Set([...perms, 'view_project', view])]
                            : perms.filter((x) => x !== view),
                        })
                      }
                    />
                    See {area.label.toLowerCase()}
                  </label>
                )
              })}
            </div>
          </fieldset>
        ))}
      </div>
    </SettingsSection>
  )
}
