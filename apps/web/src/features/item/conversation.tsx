import { useState } from 'react'
import { Loader2, MoreHorizontal } from 'lucide-react'
import { useAuthStore } from '@/stores/auth-store'
import {
  KINDS,
  useAddComment,
  useDeleteComment,
  useEditComment,
  useHistory,
} from '@/lib/taiga/items'
import type { HistoryChange, Item, ItemKind, Project } from '@/lib/taiga/types'
import { timeAgo } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { UserAvatar } from '@/components/user-avatar'
import { can } from '@/features/project/use-project'

type Props = { project: Project; kind: ItemKind; item: Item }

/** Comments and the change log, as two tabs. */
export function Conversation(props: Props) {
  const history = useHistory(props.kind, props.item.id)
  const entries = history.data ?? []
  const comments = entries.filter((e) => e.comment && !e.delete_comment_date)
  const changes = entries.filter(
    (e) => e.type !== 1 || Object.keys(e.values_diff ?? {}).some(visibleKey)
  )

  return (
    <Tabs defaultValue='comments'>
      <TabsList>
        <TabsTrigger value='comments'>
          Comments{comments.length > 0 && ` (${comments.length})`}
        </TabsTrigger>
        <TabsTrigger value='activity'>Activity</TabsTrigger>
      </TabsList>
      <TabsContent value='comments' className='mt-4'>
        {history.isPending ? (
          <Skeleton className='h-12 w-full' />
        ) : (
          <Comments {...props} comments={comments} />
        )}
      </TabsContent>
      <TabsContent value='activity' className='mt-4'>
        {history.isPending ? (
          <Skeleton className='h-12 w-full' />
        ) : (
          <Activity project={props.project} entries={changes} />
        )}
      </TabsContent>
    </Tabs>
  )
}

function Comments({
  project,
  kind,
  item,
  comments,
}: Props & { comments: HistoryChange[] }) {
  const me = useAuthStore((s) => s.session?.user.id)
  const add = useAddComment(project, kind)
  const [text, setText] = useState('')

  return (
    <div className='grid gap-4'>
      {comments.length > 0 ? (
        <ol className='grid gap-4'>
          {[...comments].reverse().map((entry) => (
            <CommentEntry
              key={entry.id}
              project={project}
              kind={kind}
              item={item}
              entry={entry}
              mine={entry.user.pk === me}
            />
          ))}
        </ol>
      ) : (
        <p className='text-sm text-muted-foreground'>No comments yet.</p>
      )}

      {can(project, KINDS[kind].perm.comment) && (
        <form
          className='grid gap-2'
          onSubmit={(e) => {
            e.preventDefault()
            const comment = text.trim()
            if (comment)
              add.mutate({ item, comment }, { onSuccess: () => setText('') })
          }}
        >
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder='Write a comment. Markdown works.'
            aria-label='New comment'
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey))
                e.currentTarget.form?.requestSubmit()
            }}
          />
          <div className='flex items-center justify-between'>
            <span className='text-xs text-muted-foreground'>
              Ctrl+Enter to send
            </span>
            <Button
              size='sm'
              type='submit'
              disabled={!text.trim() || add.isPending}
            >
              {add.isPending && <Loader2 className='animate-spin' />}
              Comment
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}

function CommentEntry({
  project,
  kind,
  item,
  entry,
  mine,
}: Props & { entry: HistoryChange; mine: boolean }) {
  const edit = useEditComment(kind, item.id)
  const remove = useDeleteComment(kind, item.id)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(entry.comment)

  return (
    <li className='group flex gap-3'>
      <UserAvatar
        user={{
          photo: entry.user.photo,
          full_name_display: entry.user.name,
          color: project.members.find((m) => m.id === entry.user.pk)?.color,
        }}
        className='mt-0.5 size-7'
      />
      <div className='min-w-0 flex-1'>
        <p className='flex items-center gap-2 text-sm'>
          <span className='font-medium'>{entry.user.name}</span>
          <time
            dateTime={entry.created_at}
            className='text-xs text-muted-foreground'
          >
            {timeAgo(entry.created_at)}
            {entry.edit_comment_date && ', edited'}
          </time>
          {mine && !editing && (
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button
                  variant='ghost'
                  size='icon'
                  className='ms-auto size-6 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100'
                  aria-label='Comment actions'
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuItem onSelect={() => setEditing(true)}>
                  Edit
                </DropdownMenuItem>
                <DropdownMenuItem
                  variant='destructive'
                  onSelect={() => remove.mutate(entry.id)}
                >
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </p>
        {editing ? (
          <form
            className='mt-1 grid gap-2'
            onSubmit={(e) => {
              e.preventDefault()
              edit.mutate(
                { entry: entry.id, comment: draft.trim() },
                { onSuccess: () => setEditing(false) }
              )
            }}
          >
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={3}
              autoFocus
              aria-label='Edit comment'
            />
            <div className='flex gap-2'>
              <Button size='sm' disabled={!draft.trim() || edit.isPending}>
                Save comment
              </Button>
              <Button
                size='sm'
                variant='ghost'
                type='button'
                onClick={() => {
                  setDraft(entry.comment)
                  setEditing(false)
                }}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div
            className='rich-text mt-1 text-sm'
            dangerouslySetInnerHTML={{ __html: entry.comment_html }}
          />
        )}
      </div>
    </li>
  )
}

/* ---------- activity ---------- */

const HIDDEN = new Set([
  'kanban_order',
  'backlog_order',
  'sprint_order',
  'taskboard_order',
  'us_order',
  'epics_order',
  'finish_date',
  'version',
])

function visibleKey(key: string) {
  return !HIDDEN.has(key)
}

const LABELS: Record<string, string> = {
  assigned_to: 'assignee',
  assigned_users: 'assignees',
  milestone: 'sprint',
  is_blocked: 'blocked',
  blocked_note: 'blocked reason',
  due_date: 'due date',
  description_diff: 'description',
  client_requirement: 'client requirement',
  team_requirement: 'team requirement',
  is_iocaine: 'iocaine',
  user_story: 'story',
  custom_attributes: 'custom fields',
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'none'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (Array.isArray(value))
    return value.length ? value.map(show).join(', ') : 'none'
  return String(value)
}

/** One readable line per changed field. */
function describe(key: string, value: unknown): string {
  const label = LABELS[key] ?? key.replace(/_/g, ' ')
  if (key === 'description_diff') return 'updated the description'
  if (key === 'attachments') {
    const v = value as { new?: unknown[]; deleted?: unknown[] }
    const parts = []
    if (v.new?.length) parts.push(`attached ${v.new.length} file(s)`)
    if (v.deleted?.length) parts.push(`removed ${v.deleted.length} file(s)`)
    return parts.join(', ') || 'changed attachments'
  }
  if (key === 'points' && value && typeof value === 'object') {
    return Object.entries(value as Record<string, [unknown, unknown]>)
      .map(
        ([role, [from, to]]) => `set ${role} points ${show(from)} → ${show(to)}`
      )
      .join('; ')
  }
  if (Array.isArray(value) && value.length === 2)
    return `changed ${label} from ${show(value[0])} to ${show(value[1])}`
  return `changed ${label}`
}

function Activity({
  project,
  entries,
}: {
  project: Project
  entries: HistoryChange[]
}) {
  if (entries.length === 0)
    return <p className='text-sm text-muted-foreground'>No changes yet.</p>
  return (
    <ol className='grid gap-3'>
      {entries.map((entry) => {
        const lines =
          entry.type === 2
            ? ['created this']
            : entry.type === 3
              ? ['deleted this']
              : Object.entries(entry.values_diff ?? {})
                  .filter(([k]) => visibleKey(k))
                  .map(([k, v]) => describe(k, v))
        if (lines.length === 0) return null
        return (
          <li key={entry.id} className='flex gap-3 text-sm'>
            <UserAvatar
              user={{
                photo: entry.user.photo,
                full_name_display: entry.user.name,
                color: project.members.find((m) => m.id === entry.user.pk)
                  ?.color,
              }}
              className='mt-0.5 size-6'
            />
            <div className='min-w-0'>
              <span className='font-medium'>{entry.user.name}</span>{' '}
              <span className='text-muted-foreground'>
                {timeAgo(entry.created_at)}
              </span>
              <ul className='mt-0.5 text-muted-foreground'>
                {lines.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
