import { useState } from 'react'
import { addDays, format, parseISO } from 'date-fns'
import { Loader2 } from 'lucide-react'
import { useCreateMilestone } from '@/lib/taiga/queries'
import { useUpdateSprint } from '@/lib/taiga/sprints'
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

type Form = { name: string; start: string; finish: string }

/** Next sprint starts the day after the last one ends, for two weeks. */
function defaults(sprints: Milestone[]): Form {
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

function SprintForm({
  title,
  description,
  initial,
  submitLabel,
  pending,
  onSubmit,
}: {
  title: string
  description: string
  initial: Form
  submitLabel: string
  pending: boolean
  onSubmit: (form: Form) => void
}) {
  const [form, setForm] = useState(initial)
  const invalid = !form.name.trim() || form.finish < form.start
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!invalid) onSubmit({ ...form, name: form.name.trim() })
      }}
      className='grid gap-4'
    >
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
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
        <Button type='submit' disabled={invalid || pending}>
          {pending && <Loader2 className='animate-spin' />}
          {submitLabel}
        </Button>
      </DialogFooter>
    </form>
  )
}

export function NewSprintDialog({
  project,
  sprints,
}: {
  project: Project
  sprints: Milestone[]
}) {
  const [open, setOpen] = useState(false)
  const create = useCreateMilestone(project)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant='outline' size='sm'>
          New sprint
        </Button>
      </DialogTrigger>
      <DialogContent className='sm:max-w-md'>
        {open && (
          <SprintForm
            title='New sprint'
            description='Stories join a sprint from the backlog.'
            initial={defaults(sprints)}
            submitLabel='Create sprint'
            pending={create.isPending}
            onSubmit={(f) =>
              create.mutate(
                {
                  name: f.name,
                  estimated_start: f.start,
                  estimated_finish: f.finish,
                },
                { onSuccess: () => setOpen(false) }
              )
            }
          />
        )}
      </DialogContent>
    </Dialog>
  )
}

export function EditSprintDialog({
  sprint,
  open,
  onOpenChange,
}: {
  sprint: Milestone
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const update = useUpdateSprint(sprint.id)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-md'>
        {open && (
          <SprintForm
            title={`Edit ${sprint.name}`}
            description='Change the name or the dates.'
            initial={{
              name: sprint.name,
              start: sprint.estimated_start,
              finish: sprint.estimated_finish,
            }}
            submitLabel='Save sprint'
            pending={update.isPending}
            onSubmit={(f) =>
              update.mutate(
                {
                  name: f.name,
                  estimated_start: f.start,
                  estimated_finish: f.finish,
                },
                { onSuccess: () => onOpenChange(false) }
              )
            }
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
