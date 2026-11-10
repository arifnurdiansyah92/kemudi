import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Loader2, MoreHorizontal } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/stores/auth-store'
import {
  KINDS,
  useAddComment,
  useDeleteComment,
  useEditComment,
  useHistory,
} from '@/lib/taiga/items'
import type { HistoryChange, Item, ItemKind, Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MentionTextarea } from '@/components/mention-textarea'
import { UserAvatar } from '@/components/user-avatar'
import { can } from '@/features/project/use-project'
import { describe, visibleKey } from './history-text'

type Props = { project: Project; kind: ItemKind; item: Item }

/** Comments and the change log, as two tabs. */
export function Conversation(props: Props) {
  const { t } = useTranslation(['item', 'common'])
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
          {comments.length > 0
            ? t('conversation.commentsCount', { count: comments.length })
            : t('common:terms.comments')}
        </TabsTrigger>
        <TabsTrigger value='activity'>{t('conversation.activity')}</TabsTrigger>
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
  const { t } = useTranslation('item')
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
        <p className='text-sm text-muted-foreground'>
          {t('conversation.noComments')}
        </p>
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
          <MentionTextarea
            project={project}
            value={text}
            onChange={setText}
            rows={3}
            placeholder={t('conversation.placeholder')}
            aria-label={t('conversation.newComment')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey))
                e.currentTarget.form?.requestSubmit()
            }}
          />
          <div className='flex items-center justify-between'>
            <span className='text-xs text-muted-foreground'>
              {t('conversation.sendHint')}
            </span>
            <Button
              size='sm'
              type='submit'
              disabled={!text.trim() || add.isPending}
            >
              {add.isPending && <Loader2 className='animate-spin' />}
              {t('conversation.comment')}
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
  const { t } = useTranslation(['item', 'common'])
  const fmt = useFormat()
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
            {entry.edit_comment_date
              ? t('conversation.edited', {
                  time: fmt.timeAgo(entry.created_at),
                })
              : fmt.timeAgo(entry.created_at)}
          </time>
          {mine && !editing && (
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button
                  variant='ghost'
                  size='icon'
                  className='ms-auto size-6 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100'
                  aria-label={t('conversation.commentActions')}
                >
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align='end'>
                <DropdownMenuItem onSelect={() => setEditing(true)}>
                  {t('common:actions.edit')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  variant='destructive'
                  onSelect={() => remove.mutate(entry.id)}
                >
                  {t('common:actions.delete')}
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
            <MentionTextarea
              project={project}
              value={draft}
              onChange={setDraft}
              rows={3}
              autoFocus
              aria-label={t('conversation.editComment')}
            />
            <div className='flex gap-2'>
              <Button size='sm' disabled={!draft.trim() || edit.isPending}>
                {t('conversation.saveComment')}
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
                {t('common:actions.cancel')}
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

function Activity({
  project,
  entries,
}: {
  project: Project
  entries: HistoryChange[]
}) {
  const { t } = useTranslation('item')
  const fmt = useFormat()
  if (entries.length === 0)
    return (
      <p className='text-sm text-muted-foreground'>
        {t('conversation.noChanges')}
      </p>
    )
  return (
    <ol className='grid gap-3'>
      {entries.map((entry) => {
        const lines =
          entry.type === 2
            ? [t('conversation.created')]
            : entry.type === 3
              ? [t('conversation.deleted')]
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
                {fmt.timeAgo(entry.created_at)}
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
