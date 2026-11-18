import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  useAgentNotes,
  useDeleteAgentNote,
  type AgentNote,
} from '@/lib/kemudi-ai/agent'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/confirm-dialog'

/** How many notes show before "Show all". */
const COMPACT = 8

/**
 * Project settings → Agent → Awak's notes: what Awak wrote down about a repo
 * for its own next runs. Members read them; admins delete a wrong one.
 */
export function AgentNotes({
  slug,
  canEdit,
}: {
  slug: string
  canEdit: boolean
}) {
  const { t } = useTranslation(['agent', 'common'])
  const f = useFormat()
  const notes = useAgentNotes(slug)
  const remove = useDeleteAgentNote(slug)
  const [showAll, setShowAll] = useState(false)
  const [deleting, setDeleting] = useState<AgentNote | null>(null)

  if (notes.isPending) return <Skeleton className='h-24 w-full' />
  if (notes.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('notes.unavailable')}
      </p>
    )
  if (notes.data.length === 0)
    return (
      <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
        {t('notes.empty')}
      </p>
    )

  const shown = showAll ? notes.data : notes.data.slice(0, COMPACT)
  return (
    <div className='grid gap-2'>
      <ul className='divide-y rounded-lg border'>
        {shown.map((note) => (
          <li key={note.id} className='flex items-start gap-3 px-4 py-2.5'>
            <div className='grid min-w-0 flex-1 gap-1'>
              <p className='text-sm break-words whitespace-pre-wrap'>
                {note.text}
              </p>
              <div className='flex flex-wrap items-center gap-2 text-xs text-muted-foreground'>
                {note.repo && (
                  <Badge variant='outline' className='font-normal'>
                    {note.repo}
                  </Badge>
                )}
                {note.at && <span>{f.timeAgo(note.at)}</span>}
              </div>
            </div>
            {canEdit && (
              <Button
                variant='ghost'
                size='icon'
                className='size-8 shrink-0 text-muted-foreground hover:text-destructive'
                aria-label={t('notes.delete')}
                onClick={() => setDeleting(note)}
              >
                <Trash2 />
              </Button>
            )}
          </li>
        ))}
      </ul>
      {notes.data.length > COMPACT && (
        <Button
          variant='ghost'
          size='sm'
          className='justify-self-start'
          aria-expanded={showAll}
          onClick={() => setShowAll(!showAll)}
        >
          {showAll
            ? t('common:actions.showLess')
            : t('notes.showAll', { count: notes.data.length })}
        </Button>
      )}
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        destructive
        title={t('notes.confirmDelete.title')}
        desc={
          <span className='grid gap-2'>
            <span>{t('notes.confirmDelete.desc')}</span>
            {deleting && (
              <span className='line-clamp-4 rounded-md bg-muted px-3 py-2 break-words text-foreground'>
                {deleting.text}
              </span>
            )}
          </span>
        }
        confirmText={t('notes.confirmDelete.confirm')}
        isLoading={remove.isPending}
        handleConfirm={() => {
          if (!deleting) return
          remove.mutate(deleting.id, {
            onSuccess: () => {
              toast.success(t('notes.deleted'))
              setDeleting(null)
            },
          })
        }}
      />
    </div>
  )
}
