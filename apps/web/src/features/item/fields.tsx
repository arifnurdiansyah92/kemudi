import { useRef, useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Check, Plus, UserRound, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { KINDS, useUpdateItem } from '@/lib/taiga/items'
import { useMilestones } from '@/lib/taiga/queries'
import type { Item, ItemKind, Project, Tag } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { UserAvatar } from '@/components/user-avatar'
import { OptionMenu } from './option-menu'

type FieldProps = {
  project: Project
  kind: ItemKind
  item: Item
  editable: boolean
}

function useSave({ project, kind, item }: FieldProps) {
  const update = useUpdateItem(project, kind)
  return (patch: Record<string, unknown>) => update.mutate({ item, patch })
}

export function StatusField(props: FieldProps) {
  const { t } = useTranslation('common')
  const save = useSave(props)
  const statuses = KINDS[props.kind]
    .statuses(props.project)
    .filter((s) => !s.is_archived || s.id === props.item.status)
  return (
    <OptionMenu
      label={t('terms.status')}
      value={props.item.status}
      options={statuses}
      disabled={!props.editable}
      onChange={(status) => status !== null && save({ status })}
    />
  )
}

/** Issue type, priority and severity share one shape. */
export function AttributeField(
  props: FieldProps & { field: 'type' | 'priority' | 'severity' }
) {
  const { t } = useTranslation('common')
  const save = useSave(props)
  const options = {
    type: props.project.issue_types,
    priority: props.project.priorities,
    severity: props.project.severities,
  }[props.field]
  const label = t(`terms.${props.field}`)
  return (
    <OptionMenu
      label={label}
      value={props.item[props.field]}
      options={[...options].sort((a, b) => a.order - b.order)}
      disabled={!props.editable}
      onChange={(id) => id !== null && save({ [props.field]: id })}
    />
  )
}

export function SprintField(props: FieldProps) {
  const { t } = useTranslation(['item', 'common'])
  const save = useSave(props)
  const { data: sprints = [] } = useMilestones(props.project.id)
  const options = sprints.map((s) => ({ id: s.id, name: s.name }))
  // A closed sprint is not in the open list; still show its name.
  if (
    props.item.milestone &&
    !options.some((o) => o.id === props.item.milestone)
  )
    options.push({
      id: props.item.milestone,
      name: props.item.milestone_name ?? t('fields.closedSprint'),
    })
  return (
    <OptionMenu
      label={t('common:terms.sprint', { count: 1 })}
      value={props.item.milestone}
      options={options}
      emptyLabel={t('common:terms.backlog')}
      disabled={!props.editable}
      onChange={(milestone) => save({ milestone })}
    />
  )
}

/** One assignee, or several for stories (assigned_users). */
export function AssigneeField(props: FieldProps) {
  const { t } = useTranslation(['item', 'common'])
  const save = useSave(props)
  const { project, item, editable } = props
  const multi = props.kind === 'userstory'
  const ids = multi
    ? item.assigned_users?.length
      ? item.assigned_users
      : item.assigned_to
        ? [item.assigned_to]
        : []
    : item.assigned_to
      ? [item.assigned_to]
      : []
  const people = ids
    .map((id) => project.members.find((m) => m.id === id))
    .filter((m) => !!m)

  const set = (next: number[]) =>
    multi
      ? save({ assigned_users: next, assigned_to: next[0] ?? null })
      : save({ assigned_to: next[0] ?? null })

  const face = (
    <span className='inline-flex min-w-0 items-center gap-2'>
      {people.length === 0 ? (
        <>
          <span className='flex size-6 items-center justify-center rounded-full border border-dashed text-muted-foreground'>
            <UserRound className='size-3.5' />
          </span>
          <span className='text-sm text-muted-foreground'>
            {t('common:status.unassigned')}
          </span>
        </>
      ) : (
        <>
          <span className='flex -space-x-1.5'>
            {people.map((m) => (
              <UserAvatar
                key={m.id}
                user={m}
                className='ring-2 ring-background'
              />
            ))}
          </span>
          <span className='truncate text-sm'>
            {people.map((m) => m.full_name_display).join(', ')}
          </span>
        </>
      )}
    </span>
  )
  if (!editable) return face

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger
        className='-mx-1 max-w-full rounded-md px-1 py-0.5 text-start outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring'
        aria-label={t('fields.changeAssignee')}
      >
        {face}
      </DropdownMenuTrigger>
      <DropdownMenuContent align='start' className='max-h-80 min-w-56'>
        {project.members
          .filter((m) => m.is_active)
          .map((member) => {
            const on = ids.includes(member.id)
            return (
              <DropdownMenuItem
                key={member.id}
                onSelect={(e) => {
                  if (multi) {
                    e.preventDefault()
                    set(
                      on
                        ? ids.filter((i) => i !== member.id)
                        : [...ids, member.id]
                    )
                  } else set([member.id])
                }}
              >
                <UserAvatar user={member} className='size-5' />
                <span className='truncate'>{member.full_name_display}</span>
                {on && <Check className='ms-auto' />}
              </DropdownMenuItem>
            )
          })}
        {ids.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => set([])}>
              {multi && ids.length > 1
                ? t('fields.unassignAll')
                : t('fields.unassign')}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function TagsField(props: FieldProps) {
  const { t } = useTranslation(['item', 'common'])
  const save = useSave(props)
  const { project, item, editable } = props
  const [adding, setAdding] = useState(false)
  const [value, setValue] = useState('')
  const known = Object.keys(project.tags_colors).sort()

  const setTags = (tags: Tag[]) => save({ tags })
  const add = () => {
    const name = value.trim().toLowerCase()
    setValue('')
    if (!name || item.tags.some(([tag]) => tag === name)) return
    setTags([...item.tags, [name, project.tags_colors[name] ?? null]])
  }

  return (
    <div className='flex flex-wrap items-center gap-1'>
      {item.tags.map(([name, color]) => {
        const c = color ?? project.tags_colors[name]
        return (
          <span
            key={name}
            className='inline-flex h-6 items-center gap-1 rounded-sm bg-muted ps-1.5 pe-1 text-xs'
          >
            {c && (
              <span
                aria-hidden='true'
                className='size-1.5 rounded-full'
                style={{ backgroundColor: c }}
              />
            )}
            {name}
            {editable && (
              <button
                aria-label={t('fields.removeTag', { name })}
                className='rounded text-muted-foreground hover:text-foreground'
                onClick={() =>
                  setTags(item.tags.filter(([tag]) => tag !== name))
                }
              >
                <X className='size-3' />
              </button>
            )}
          </span>
        )
      })}
      {editable &&
        (adding ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              add()
            }}
          >
            <Input
              autoFocus
              list='project-tags'
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onBlur={() => {
                add()
                setAdding(false)
              }}
              onKeyDown={(e) => e.key === 'Escape' && setAdding(false)}
              placeholder={t('fields.tagName')}
              aria-label={t('fields.newTag')}
              className='h-6 w-32 px-2 text-xs'
            />
            <datalist id='project-tags'>
              {known.map((tag) => (
                <option key={tag} value={tag} />
              ))}
            </datalist>
          </form>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className='inline-flex h-6 items-center gap-1 rounded-sm border border-dashed px-1.5 text-xs text-muted-foreground hover:bg-accent'
          >
            <Plus className='size-3' />
            {t('fields.addTag')}
          </button>
        ))}
      {!editable && item.tags.length === 0 && (
        <span className='text-sm text-muted-foreground'>
          {t('common:status.none')}
        </span>
      )}
    </div>
  )
}

export function DueDateField(props: FieldProps) {
  const { t } = useTranslation(['item', 'common'])
  const fmt = useFormat()
  const save = useSave(props)
  const { item, editable } = props
  const reason =
    (item as Item & { due_date_reason?: string }).due_date_reason ?? ''
  if (!editable)
    return (
      <span className='text-sm'>
        {item.due_date ? (
          fmt.date(item.due_date)
        ) : (
          <span className='text-muted-foreground'>
            {t('common:status.none')}
          </span>
        )}
        {item.due_date && reason && (
          <span className='text-muted-foreground'>, {reason}</span>
        )}
      </span>
    )
  return (
    <span className='inline-flex flex-wrap items-center gap-1'>
      <Input
        type='date'
        aria-label={t('common:terms.dueDate')}
        value={item.due_date ?? ''}
        onChange={(e) => save({ due_date: e.target.value || null })}
        className={cn(
          'h-7 w-40 text-xs',
          !item.due_date && 'text-muted-foreground'
        )}
      />
      {item.due_date && (
        <Button
          variant='ghost'
          size='icon'
          className='size-7'
          aria-label={t('fields.clearDueDate')}
          onClick={() => save({ due_date: null, due_date_reason: '' })}
        >
          <X />
        </Button>
      )}
      {item.due_date && (
        <Input
          aria-label={t('fields.dueDateReason')}
          placeholder={t('fields.dueDateReasonPlaceholder')}
          defaultValue={reason}
          onBlur={(e) =>
            e.target.value !== reason &&
            save({ due_date_reason: e.target.value })
          }
          className='h-7 min-w-40 flex-1 text-xs'
        />
      )}
    </span>
  )
}

/** Who gets notified about changes; members can add others. */
export function WatchersField(props: FieldProps) {
  const { t } = useTranslation('item')
  const save = useSave(props)
  const { project, item, editable } = props
  const watchers = item.watchers
    .map((id) => project.members.find((m) => m.id === id))
    .filter((m) => !!m)
  const set = (ids: number[]) => save({ watchers: ids })

  const face = (
    <span className='inline-flex min-w-0 items-center gap-2'>
      {watchers.length === 0 ? (
        <span className='text-sm text-muted-foreground'>
          {t('fields.nobody')}
        </span>
      ) : (
        <>
          <span className='flex -space-x-1.5'>
            {watchers.slice(0, 6).map((m) => (
              <UserAvatar
                key={m.id}
                user={m}
                className='ring-2 ring-background'
              />
            ))}
          </span>
          <span className='truncate text-sm'>
            {watchers.map((m) => m.full_name_display).join(', ')}
          </span>
        </>
      )}
    </span>
  )
  if (!editable) return face
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger
        className='-mx-1 max-w-full rounded-md px-1 py-0.5 text-start outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring'
        aria-label={t('fields.changeWatchers')}
      >
        {face}
      </DropdownMenuTrigger>
      <DropdownMenuContent align='start' className='max-h-80 min-w-56'>
        {project.members
          .filter((m) => m.is_active)
          .map((member) => {
            const on = item.watchers.includes(member.id)
            return (
              <DropdownMenuItem
                key={member.id}
                onSelect={(e) => {
                  e.preventDefault()
                  set(
                    on
                      ? item.watchers.filter((i) => i !== member.id)
                      : [...item.watchers, member.id]
                  )
                }}
              >
                <UserAvatar user={member} className='size-5' />
                <span className='truncate'>{member.full_name_display}</span>
                {on && <Check className='ms-auto' />}
              </DropdownMenuItem>
            )
          })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Points per computable role, as Taiga estimates stories. */
export function PointsField(props: FieldProps) {
  const { t } = useTranslation('item')
  const save = useSave(props)
  const { project, item, editable } = props
  const roles = project.roles
    .filter((r) => r.computable)
    .sort((a, b) => a.order - b.order)
  const points = [...project.points].sort((a, b) => a.order - b.order)
  const current = item.points ?? {}

  return (
    <div className='grid gap-1.5'>
      <div className='flex flex-wrap gap-1.5'>
        {roles.map((role) => (
          <span key={role.id} className='inline-flex items-center gap-1.5'>
            <span className='text-xs text-muted-foreground'>{role.name}</span>
            <OptionMenu
              label={t('fields.rolePoints', { role: role.name })}
              value={current[role.id]}
              options={points}
              disabled={!editable}
              onChange={(pointId) =>
                pointId !== null &&
                save({ points: { ...current, [role.id]: pointId } })
              }
            />
          </span>
        ))}
      </div>
      <span className='text-xs text-muted-foreground tabular-nums'>
        {t('fields.totalPoints', {
          total: item.total_points ?? t('fields.notEstimated'),
        })}
      </span>
    </div>
  )
}

export function FlagsField(props: FieldProps) {
  const { t } = useTranslation('item')
  const save = useSave(props)
  const { item, editable } = props
  const flags = [
    ['client_requirement', t('fields.clientRequirement')],
    ['team_requirement', t('fields.teamRequirement')],
  ] as const
  return (
    <div className='flex flex-wrap gap-1.5'>
      {flags.map(([key, label]) => (
        <button
          key={key}
          disabled={!editable}
          aria-pressed={!!item[key]}
          onClick={() => save({ [key]: !item[key] })}
          className={cn(
            'h-7 rounded-full border px-2.5 text-xs',
            item[key]
              ? 'border-primary bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-accent',
            !editable && 'cursor-default'
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export function IocaineField(props: FieldProps) {
  const { t } = useTranslation('item')
  const save = useSave(props)
  const on = !!props.item.is_iocaine
  return (
    <button
      disabled={!props.editable}
      aria-pressed={on}
      onClick={() => save({ is_iocaine: !on })}
      title={t('fields.iocaineHint')}
      className={cn(
        'h-7 rounded-full border px-2.5 text-xs',
        on
          ? 'border-primary bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:bg-accent'
      )}
    >
      {t('fields.iocaine')}
    </button>
  )
}

export function ColorField(props: FieldProps) {
  const { t } = useTranslation('item')
  const save = useSave(props)
  const [color, setColor] = useState(props.item.color ?? '#999999')
  const timer = useRef<number | undefined>(undefined)
  return (
    <input
      type='color'
      aria-label={t('fields.epicColour')}
      disabled={!props.editable}
      value={color}
      onChange={(e) => {
        // The picker fires on every drag step; save once it settles.
        const next = e.target.value
        setColor(next)
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => save({ color: next }), 500)
      }}
      className='h-7 w-12 cursor-pointer rounded border bg-transparent'
    />
  )
}
