import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation(['backlog', 'common'])
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const create = useBulkCreateStories(project)
  const lines = text.split('\n').filter((l) => l.trim()).length

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size='sm' variant='outline'>
          {t('backlog.bulkAdd.trigger')}
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
            <DialogTitle>{t('backlog.bulkAdd.title')}</DialogTitle>
            <DialogDescription>
              {t('backlog.bulkAdd.description')}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            autoFocus
            aria-label={t('backlog.bulkAdd.inputLabel')}
            placeholder={t('backlog.bulkAdd.placeholder')}
          />
          <DialogFooter>
            <Button type='submit' disabled={!lines || create.isPending}>
              {create.isPending && <Loader2 className='animate-spin' />}
              {lines > 1
                ? t('backlog.bulkAdd.submitMany', { lines })
                : t('backlog.bulkAdd.submitOne')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
