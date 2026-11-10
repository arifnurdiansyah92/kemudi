import { useState } from 'react'
import { Eye, Link2, MoreHorizontal, ThumbsUp } from 'lucide-react'
import { toast } from 'sonner'
import { usePromote } from '@/lib/taiga/issues'
import {
  KINDS,
  useDeleteItem,
  useToggle,
  useUpdateItem,
} from '@/lib/taiga/items'
import type { Item, ItemKind, Project } from '@/lib/taiga/types'
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { can, useRefParam } from '@/features/project/use-project'

type Props = {
  project: Project
  kind: ItemKind
  item: Item
  onDeleted: () => void
}

/** Watch and vote buttons, and a menu for the rest. */
export function ItemActions({ project, kind, item, onDeleted }: Props) {
  const watch = useToggle(project, kind, 'watch')
  const vote = useToggle(project, kind, 'vote')
  const update = useUpdateItem(project, kind)
  const remove = useDeleteItem(project, kind)
  const promote = usePromote(project, kind)
  const { open } = useRefParam()
  const [blocking, setBlocking] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const label = KINDS[kind].label
  const editable = can(project, KINDS[kind].perm.modify)

  return (
    <div className='flex items-center gap-1'>
      <Button
        variant='ghost'
        size='sm'
        className='h-7 gap-1.5 px-2 text-xs'
        aria-pressed={item.is_watcher}
        onClick={() => watch.mutate(item)}
        title={item.is_watcher ? 'Stop watching' : 'Watch for changes'}
      >
        <Eye className={cn(item.is_watcher && 'text-brass')} />
        {item.is_watcher ? 'Watching' : 'Watch'}
        <span className='text-muted-foreground tabular-nums'>
          {item.total_watchers}
        </span>
      </Button>
      {KINDS[kind].voting && (
        <Button
          variant='ghost'
          size='sm'
          className={cn(
            'h-7 gap-1.5 px-2 text-xs',
            item.is_voter && 'text-brass'
          )}
          aria-pressed={item.is_voter}
          onClick={() => vote.mutate(item)}
          title={item.is_voter ? 'Remove your vote' : 'Vote for this'}
        >
          <ThumbsUp />
          <span className='tabular-nums'>{item.total_voters ?? 0}</span>
        </Button>
      )}

      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant='ghost'
            size='icon'
            className='size-7'
            aria-label={`More actions for ${label.toLowerCase()} #${item.ref}`}
          >
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align='end' className='min-w-44'>
          <DropdownMenuItem
            onSelect={() => {
              navigator.clipboard
                ?.writeText(window.location.href)
                .then(() => toast.success('Link copied'))
            }}
          >
            <Link2 />
            Copy link
          </DropdownMenuItem>
          {editable &&
            (item.is_blocked ? (
              <DropdownMenuItem
                onSelect={() =>
                  update.mutate({
                    item,
                    patch: { is_blocked: false, blocked_note: '' },
                  })
                }
              >
                Unblock
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={() => setBlocking(true)}>
                Mark as blocked
              </DropdownMenuItem>
            ))}
          {(kind === 'issue' || kind === 'task') && can(project, 'add_us') && (
            <DropdownMenuItem
              onSelect={() =>
                promote.mutate(item, {
                  onSuccess: (refs) => {
                    toast.success(
                      kind === 'task'
                        ? `Task turned into story #${refs[0]}`
                        : `Story #${refs[0]} created from this issue`
                    )
                    if (refs[0]) open(refs[0])
                  },
                })
              }
            >
              Promote to story
            </DropdownMenuItem>
          )}
          {can(project, KINDS[kind].perm.delete) && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant='destructive'
                onSelect={() => setDeleting(true)}
              >
                Delete {label.toLowerCase()}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <BlockDialog
        open={blocking}
        onOpenChange={setBlocking}
        onBlock={(note) =>
          update.mutate(
            { item, patch: { is_blocked: true, blocked_note: note } },
            { onSuccess: () => setBlocking(false) }
          )
        }
      />
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${label.toLowerCase()} #${item.ref}?`}
        desc={`"${item.subject}" and its comments and attachments are deleted for everyone. This cannot be undone.`}
        confirmText={`Delete ${label.toLowerCase()}`}
        destructive
        isLoading={remove.isPending}
        handleConfirm={() =>
          remove.mutate(item, {
            onSuccess: () => {
              setDeleting(false)
              onDeleted()
            },
          })
        }
      />
    </div>
  )
}

function BlockDialog({
  open,
  onOpenChange,
  onBlock,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onBlock: (note: string) => void
}) {
  const [note, setNote] = useState('')
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <form
          className='grid gap-4'
          onSubmit={(e) => {
            e.preventDefault()
            onBlock(note.trim())
            setNote('')
          }}
        >
          <DialogHeader>
            <DialogTitle>Mark as blocked</DialogTitle>
            <DialogDescription>
              Say what is in the way, so whoever can unblock it knows.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            autoFocus
            aria-label='What is blocking it'
            placeholder='Waiting for the API change in #42'
          />
          <DialogFooter>
            <Button type='submit'>Mark as blocked</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
