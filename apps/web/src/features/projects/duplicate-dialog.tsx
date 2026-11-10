import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useDuplicateProject } from '@/lib/taiga/projects'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Source = {
  id: number
  name: string
  description: string
  is_private: boolean
  members?: { id: number; full_name_display: string; is_active?: boolean }[]
}

/** Copies a project's settings, statuses and roles into a new, empty project. */
export function DuplicateProjectDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Source
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useTranslation('home')
  const navigate = useNavigate()
  const duplicate = useDuplicateProject()
  const [name, setName] = useState(() =>
    t('projects.duplicate.copyName', { name: project.name })
  )
  const members = (project.members ?? []).filter((m) => m.is_active !== false)
  const [users, setUsers] = useState<number[]>(members.map((m) => m.id))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        <form
          className='grid gap-4'
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim()) return
            duplicate.mutate(
              {
                project,
                name: name.trim(),
                description: project.description || name.trim(),
                is_private: project.is_private,
                users,
              },
              {
                onSuccess: (p) => {
                  onOpenChange(false)
                  navigate({ to: '/p/$slug', params: { slug: p.slug } })
                },
              }
            )
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {t('projects.duplicate.title', { name: project.name })}
            </DialogTitle>
            <DialogDescription>
              {t('projects.duplicate.description')}
            </DialogDescription>
          </DialogHeader>
          <div className='grid gap-1.5'>
            <Label htmlFor='dup-name'>
              {t('projects.duplicate.nameLabel')}
            </Label>
            <Input
              id='dup-name'
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          {members.length > 0 && (
            <fieldset className='grid gap-2'>
              <legend className='mb-1 text-sm font-medium'>
                {t('projects.duplicate.membersLegend')}
              </legend>
              {members.map((m) => (
                <label key={m.id} className='flex items-center gap-2 text-sm'>
                  <Checkbox
                    checked={users.includes(m.id)}
                    onCheckedChange={(v) =>
                      setUsers((u) =>
                        v ? [...u, m.id] : u.filter((id) => id !== m.id)
                      )
                    }
                  />
                  {m.full_name_display}
                </label>
              ))}
            </fieldset>
          )}
          <DialogFooter>
            <Button
              type='submit'
              disabled={!name.trim() || duplicate.isPending}
            >
              {duplicate.isPending && <Loader2 className='animate-spin' />}
              {t('projects.duplicate.submit')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
