import { useRef, useState } from 'react'
import { FileText, Loader2, Paperclip, Trash2 } from 'lucide-react'
import {
  KINDS,
  type AttachableKind,
  useAttachments,
  useDeleteAttachment,
  useUploadAttachment,
} from '@/lib/taiga/items'
import type { Project } from '@/lib/taiga/types'
import { cn, formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { can } from '@/features/project/use-project'

type AttachmentsProps = {
  project: Project
  kind: AttachableKind
  item: { id: number }
}

export function Attachments({ project, kind, item }: AttachmentsProps) {
  const list = useAttachments(project, kind, item.id)
  const upload = useUploadAttachment(project, kind, item.id)
  const remove = useDeleteAttachment(kind, item.id)
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const editable = can(
    project,
    kind === 'wiki' ? 'modify_wiki_page' : KINDS[kind].perm.modify
  )

  const send = (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) upload.mutate(file)
  }

  if (list.isPending) return <Skeleton className='h-10 w-full' />
  const files = (list.data ?? []).filter((a) => !a.is_deprecated)

  return (
    <div
      className={cn(
        'grid gap-2 rounded-md',
        dragging && 'ring-2 ring-ring ring-offset-4 ring-offset-background'
      )}
      onDragOver={(e) => {
        if (!editable) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        if (!editable) return
        e.preventDefault()
        setDragging(false)
        send(e.dataTransfer.files)
      }}
    >
      {files.length > 0 && (
        <ul className='grid gap-1'>
          {files.map((file) => (
            <li
              key={file.id}
              className='group flex items-center gap-3 rounded-md px-1 py-1 text-sm hover:bg-accent/50'
            >
              {file.thumbnail_card_url ? (
                <img
                  src={file.thumbnail_card_url}
                  alt=''
                  className='size-8 shrink-0 rounded object-cover'
                />
              ) : (
                <span className='flex size-8 shrink-0 items-center justify-center rounded bg-muted'>
                  <FileText className='size-4 text-muted-foreground' />
                </span>
              )}
              <a
                href={file.url}
                target='_blank'
                rel='noreferrer'
                className='min-w-0 flex-1 truncate hover:underline hover:underline-offset-4'
              >
                {file.name}
              </a>
              <span className='shrink-0 text-xs text-muted-foreground tabular-nums'>
                {formatBytes(file.size)}
              </span>
              {editable && (
                <Button
                  variant='ghost'
                  size='icon'
                  className='size-7 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
                  aria-label={`Delete ${file.name}`}
                  onClick={() => remove.mutate(file)}
                >
                  <Trash2 />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {editable ? (
        <>
          <input
            ref={input}
            type='file'
            multiple
            hidden
            onChange={(e) => {
              send(e.target.files)
              e.target.value = ''
            }}
          />
          <button
            onClick={() => input.current?.click()}
            className='flex items-center justify-center gap-2 rounded-md border border-dashed px-3 py-3 text-sm text-muted-foreground hover:bg-accent/50'
          >
            {upload.isPending ? (
              <Loader2 className='size-4 animate-spin' />
            ) : (
              <Paperclip className='size-4' />
            )}
            {upload.isPending ? 'Uploading…' : 'Attach files or drop them here'}
          </button>
        </>
      ) : (
        files.length === 0 && (
          <p className='text-sm text-muted-foreground'>No attachments.</p>
        )
      )}
    </div>
  )
}
