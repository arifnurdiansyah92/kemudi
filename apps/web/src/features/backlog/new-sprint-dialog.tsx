import { useState } from 'react'
import { addDays, format, parseISO } from 'date-fns'
import { Loader2 } from 'lucide-react'
import { useCreateMilestone } from '@/lib/taiga/queries'
import type { Milestone, Project } from '@/lib/taiga/types'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const iso = (d: Date) => format(d, 'yyyy-MM-dd')

/** Next sprint starts the day after the last one ends, for two weeks. */
function defaults(sprints: Milestone[]) {
  const last = [...sprints].sort((a, b) =>
    a.estimated_finish.localeCompare(b.estimated_finish)
  )[sprints.length - 1]
  const start = last ? addDays(parseISO(last.estimated_finish), 1) : new Date()
  return {
    name: `Sprint ${sprints.length + 1}`,
    start: iso(start),
    finish: iso(addDays(start, 13)),
  }
}

export function NewSprintDialog({
  project,
  sprints,
}: {
  project: Project
  sprints: Milestone[]
}) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(() => defaults(sprints))
  const create = useCreateMilestone(project)
  const invalid = !form.name.trim() || form.finish < form.start

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setForm(defaults(sprints))
        setOpen(next)
      }}
    >
      <DialogTrigger asChild>
        <Button variant='outline' size='sm'>
          New sprint
        </Button>
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (invalid) return
            create.mutate(
              {
                name: form.name.trim(),
                estimated_start: form.start,
                estimated_finish: form.finish,
              },
              { onSuccess: () => setOpen(false) }
            )
          }}
          className='grid gap-4'
        >
          <DialogHeader>
            <DialogTitle>New sprint</DialogTitle>
            <DialogDescription>
              Stories join a sprint from the backlog.
            </DialogDescription>
          </DialogHeader>
          <div className='grid gap-2'>
            <Label htmlFor='sprint-name'>Name</Label>
            <Input
              id='sprint-name'
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className='grid grid-cols-2 gap-3'>
            <div className='grid gap-2'>
              <Label htmlFor='sprint-start'>Starts</Label>
              <Input
                id='sprint-start'
                type='date'
                value={form.start}
                onChange={(e) => setForm({ ...form, start: e.target.value })}
              />
            </div>
            <div className='grid gap-2'>
              <Label htmlFor='sprint-finish'>Ends</Label>
              <Input
                id='sprint-finish'
                type='date'
                value={form.finish}
                min={form.start}
                onChange={(e) => setForm({ ...form, finish: e.target.value })}
              />
            </div>
          </div>
          {form.finish < form.start && (
            <p className='text-sm text-destructive'>
              The end date must be on or after the start date.
            </p>
          )}
          <DialogFooter>
            <Button type='submit' disabled={invalid || create.isPending}>
              {create.isPending && <Loader2 className='animate-spin' />}
              Create sprint
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
