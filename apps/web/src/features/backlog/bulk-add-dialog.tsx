import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useBulkCreateStories } from '@/lib/taiga/sprints'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

/** Paste a list: each line becomes a story at the end of the backlog. */
export function BulkAddDialog({ project }: { project: Project }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const create = useBulkCreateStories(project)
  const lines = text.split('\n').filter((l) => l.trim()).length

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline'>
          Add several
        </Button>
      </DialogTrigger>
      <DialogContent className='sm:max-w-lg'>
        <form
          className='grid gap-4'
          onSubmit={(e) => {
            e.preventDefault()
            if (!lines) return
            create.mutate(
              { text },
              {
                onSuccess: () => {
                  setText('')
                  setOpen(false)
                },
              }
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>Add several stories</DialogTitle>
            <DialogDescription>
              One story per line. They go to the end of the backlog.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            autoFocus
            aria-label='Stories, one per line'
            placeholder={'Export the report as CSV\nShow totals per team'}
          />
          <DialogFooter>
            <Button type='submit' disabled={!lines || create.isPending}>
              {create.isPending && <Loader2 className='animate-spin' />}
              {lines > 1 ? `Add ${lines} stories` : 'Add story'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
