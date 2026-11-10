import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

/** Sends a message to a project's admins (projects that allow contact). */
export function ContactDialog({
  project,
  open,
  onOpenChange,
}: {
  project: { id: number; name: string }
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation('home')
  const [text, setText] = useState('')
  const send = useMutation({
    mutationFn: () =>
      api.post('/contact', { project: project.id, comment: text.trim() }),
    onSuccess: () => {
      toast.success(t('projects.contact.sent', { name: project.name }))
      setText('')
      onOpenChange(false)
    },
    onError: onFail,
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <form
          className='grid gap-4'
          onSubmit={(e) => {
            e.preventDefault()
            if (text.trim()) send.mutate()
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {t('projects.contact.title', { name: project.name })}
            </DialogTitle>
            <DialogDescription>
              {t('projects.contact.description')}
            </DialogDescription>
          </DialogHeader>
          <Textarea
            rows={5}
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-label={t('projects.contact.message')}
            placeholder={t('projects.contact.placeholder')}
          />
          <DialogFooter>
            <Button type='submit' disabled={!text.trim() || send.isPending}>
              {send.isPending && <Loader2 className='animate-spin' />}
              {t('projects.contact.send')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
