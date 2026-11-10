import { Check, ChevronDown, UserRound } from 'lucide-react'
import { useUpdateStory } from '@/lib/taiga/queries'
import type { Member, Project, UserStory } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { UserAvatar } from '@/components/user-avatar'
import { can } from '@/features/project/use-project'

export function StatusDot({ color }: { color: string }) {
  return (
    <span
      aria-hidden='true'
      className='size-2 shrink-0 rounded-full'
      style={{ backgroundColor: color }}
    />
  )
}

/** Status shown as a small pill; a menu to change it when allowed. */
export function StatusMenu({
  project,
  story,
  className,
  compact = false,
}: {
  project: Project
  story: UserStory
  className?: string
  /** Dot only, for narrow rows. The name stays available to screen readers. */
  compact?: boolean
}) {
  const update = useUpdateStory(project)
  const info = story.status_extra_info
  const editable = can(project, 'modify_us')
  const pill = compact ? (
    <span
      title={info.name}
      className={cn(
        'inline-flex size-6 items-center justify-center rounded-full',
        editable && 'hover:bg-accent',
        className
      )}
    >
      <StatusDot color={info.color} />
      <span className='sr-only'>{info.name}</span>
    </span>
  ) : (
    <span
      className={cn(
        'inline-flex h-6 max-w-40 items-center gap-1.5 rounded-full border bg-background px-2 text-xs font-medium',
        editable && 'hover:bg-accent',
        className
      )}
    >
      <StatusDot color={info.color} />
      <span className='truncate'>{info.name}</span>
      {editable && <ChevronDown className='size-3 text-muted-foreground' />}
    </span>
  )
  if (!editable) return pill

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger
        className='rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring'
        aria-label={`Status: ${info.name}. Change status`}
      >
        {pill}
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='min-w-44'>
        {project.us_statuses
          .filter((s) => !s.is_archived)
          .map((status) => (
            <DropdownMenuItem
              key={status.id}
              onSelect={() =>
                status.id !== story.status &&
                update.mutate({ id: story.id, patch: { status: status.id } })
              }
            >
              <StatusDot color={status.color} />
              {status.name}
              {status.id === story.status && <Check className='ms-auto' />}
            </DropdownMenuItem>
          ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function Points({ value }: { value: number | null }) {
  if (value === null)
    return (
      <span className='text-muted-foreground' aria-label='Not estimated'>
        –
      </span>
    )
  return (
    <span className='tabular-nums'>
      {Number.isInteger(value) ? value : value.toFixed(1)}
    </span>
  )
}

/** Assignee avatar; a menu of project members when the user may edit. */
export function AssigneeMenu({
  project,
  story,
  showName = false,
}: {
  project: Project
  story: UserStory
  showName?: boolean
}) {
  const update = useUpdateStory(project)
  const assignee = project.members.find((m) => m.id === story.assigned_to)
  const editable = can(project, 'modify_us')

  const face = (
    <span className='inline-flex items-center gap-2'>
      {assignee ? (
        <UserAvatar user={assignee} />
      ) : (
        <span className='flex size-6 items-center justify-center rounded-full border border-dashed text-muted-foreground'>
          <UserRound className='size-3.5' />
        </span>
      )}
      {showName && (
        <span className={cn('text-sm', !assignee && 'text-muted-foreground')}>
          {assignee?.full_name_display ?? 'Unassigned'}
        </span>
      )}
    </span>
  )
  const label = assignee
    ? `Assigned to ${assignee.full_name_display}`
    : 'Unassigned'

  if (!editable)
    return showName ? (
      face
    ) : (
      <Tooltip>
        <TooltipTrigger asChild>
          <span aria-label={label}>{face}</span>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    )

  const choose = (member: Member | null) =>
    update.mutate({
      id: story.id,
      patch: { assigned_to: member?.id ?? null },
    })

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger
        className='rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring'
        aria-label={`${label}. Change assignee`}
      >
        {face}
      </DropdownMenuTrigger>
      <DropdownMenuContent align='end' className='max-h-80 min-w-52'>
        {project.members
          .filter((m) => m.is_active)
          .map((member) => (
            <DropdownMenuItem key={member.id} onSelect={() => choose(member)}>
              <UserAvatar user={member} className='size-5' />
              <span className='truncate'>{member.full_name_display}</span>
              {member.id === story.assigned_to && <Check className='ms-auto' />}
            </DropdownMenuItem>
          ))}
        {assignee && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => choose(null)}>
              Unassign
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function TagList({
  project,
  tags,
  max = 3,
}: {
  project: Project
  tags: UserStory['tags']
  max?: number
}) {
  if (!tags.length) return null
  const shown = tags.slice(0, max)
  return (
    <span className='inline-flex min-w-0 items-center gap-1'>
      {shown.map(([name, color]) => {
        const c = color ?? project.tags_colors[name] ?? null
        return (
          <span
            key={name}
            className='inline-flex h-5 max-w-28 items-center gap-1 rounded-sm bg-muted px-1.5 text-[0.6875rem] text-muted-foreground'
          >
            {c && (
              <span
                aria-hidden='true'
                className='size-1.5 shrink-0 rounded-full'
                style={{ backgroundColor: c }}
              />
            )}
            <span className='truncate'>{name}</span>
          </span>
        )
      })}
      {tags.length > max && (
        <span className='text-[0.6875rem] text-muted-foreground'>
          +{tags.length - max}
        </span>
      )}
    </span>
  )
}
