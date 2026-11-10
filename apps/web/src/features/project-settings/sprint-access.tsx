import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import { useMilestones } from '@/lib/taiga/queries'
import { useClosedSprints } from '@/lib/taiga/sprints'
import type { Id, Milestone, Project } from '@/lib/taiga/types'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

interface Role {
  id: Id
  name: string
  order: number
  permissions: string[]
  members_count: number
}

const PREFIX = 'sprint:'
const sprintIds = (perms: string[]) =>
  perms
    .filter((p) => p.startsWith(PREFIX))
    .map((p) => Number(p.slice(PREFIX.length)))

/**
 * Kemudi's sprint_access backend: a role limited to some sprints sees only
 * those sprints and their stories, tasks and issues. Backlog items are
 * never hidden; project admins are never limited.
 */
export function SprintAccessSettings() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  const qc = useQueryClient()
  const roles = useQuery({
    queryKey: ['roles', project.id],
    queryFn: async () =>
      (
        await api.get<Role[]>('/roles', { params: { project: project.id } })
      ).data.sort((a, b) => a.order - b.order),
  })
  const open = useMilestones(project.id)
  const closed = useClosedSprints(project.id)
  const save = useMutation({
    mutationFn: ({ role, ids }: { role: Role; ids: Id[] }) =>
      api.patch(`/roles/${role.id}`, { sprint_access: ids }),
    onMutate: ({ role, ids }) =>
      qc.setQueryData<Role[]>(['roles', project.id], (list) =>
        list?.map((r) =>
          r.id === role.id
            ? {
                ...r,
                permissions: [
                  ...r.permissions.filter((p) => !p.startsWith(PREFIX)),
                  ...ids.map((id) => `${PREFIX}${id}`),
                ],
              }
            : r
        )
      ),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['roles', project.id] }),
  })

  const sprints: Milestone[] = [
    ...(open.data ?? []),
    ...(closed.data ?? []),
  ].sort((a, b) => b.estimated_start.localeCompare(a.estimated_start))

  return (
    <SettingsSection
      title={t('sprintAccess.title')}
      description={t('sprintAccess.description')}
    >
      {roles.isPending || open.isPending ? (
        <Skeleton className='h-32 w-full' />
      ) : sprints.length === 0 ? (
        <p className='text-sm text-muted-foreground'>
          {t('sprintAccess.empty')}
        </p>
      ) : (
        <ul className='grid gap-4'>
          {(roles.data ?? []).map((role) => (
            <RoleAccess
              key={role.id}
              project={project}
              role={role}
              sprints={sprints}
              onSave={(ids) => save.mutate({ role, ids })}
            />
          ))}
        </ul>
      )}
    </SettingsSection>
  )
}

function RoleAccess({
  role,
  sprints,
  onSave,
}: {
  project: Project
  role: Role
  sprints: Milestone[]
  onSave: (ids: Id[]) => void
}) {
  const { t } = useTranslation(['admin', 'common'])
  const ids = sprintIds(role.permissions)
  const limited = ids.length > 0
  return (
    <li className='rounded-md border p-3'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <p className='text-sm font-medium'>
          {role.name}
          <span className='ms-2 text-xs font-normal text-muted-foreground'>
            {t('sprintAccess.members', { count: role.members_count })}
          </span>
        </p>
        <label className='flex items-center gap-2 text-sm'>
          <Switch
            checked={limited}
            onCheckedChange={(on) => onSave(on ? [sprints[0].id] : [])}
          />
          {limited
            ? t('sprintAccess.only', { count: ids.length })
            : t('sprintAccess.all')}
        </label>
      </div>
      {limited && (
        <div className='mt-3 flex flex-wrap gap-x-5 gap-y-2'>
          {sprints.map((s) => (
            <label key={s.id} className='flex items-center gap-2 text-sm'>
              <Checkbox
                checked={ids.includes(s.id)}
                onCheckedChange={(v) => {
                  const next = v
                    ? [...ids, s.id]
                    : ids.filter((x) => x !== s.id)
                  // Unticking the last sprint would mean "all"; keep at least one.
                  if (next.length) onSave(next)
                }}
              />
              {s.name}
              {s.closed && (
                <span className='text-xs text-muted-foreground'>
                  {t('sprintAccess.closed')}
                </span>
              )}
            </label>
          ))}
        </div>
      )}
    </li>
  )
}
