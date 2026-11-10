import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Columns3, ListOrdered, Loader2 } from 'lucide-react'
import { useCreateProject, useProjectTemplates } from '@/lib/taiga/projects'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { ImporterLinks } from '@/features/importers'
import { ImportDump } from './import-dump'

const TEMPLATE_COPY: Record<
  string,
  { icon: React.ElementType; blurb: string }
> = {
  scrum: {
    icon: ListOrdered,
    blurb:
      'A prioritised backlog, planned into time-boxed sprints with a taskboard.',
  },
  kanban: {
    icon: Columns3,
    blurb:
      'A board of columns that work flows through, with limits on work in progress.',
  },
}

export function NewProject() {
  const navigate = useNavigate()
  const templates = useProjectTemplates()
  const create = useCreateProject()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [template, setTemplate] = useState<number | null>(null)
  const [isPrivate, setPrivate] = useState(true)
  const chosen = template ?? templates.data?.[0]?.id ?? null

  return (
    <>
      <AppHeader
        crumbs={[
          { label: 'Projects', to: '/projects' },
          { label: 'New project' },
        ]}
      />
      <Main className='max-w-2xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>New project</h1>
        <form
          className='mt-8 grid gap-6'
          onSubmit={(e) => {
            e.preventDefault()
            if (!name.trim() || !chosen) return
            create.mutate(
              {
                name: name.trim(),
                description: description.trim() || name.trim(),
                creation_template: chosen,
                is_private: isPrivate,
              },
              {
                onSuccess: (p) =>
                  navigate({ to: '/p/$slug', params: { slug: p.slug } }),
              }
            )
          }}
        >
          <fieldset>
            <legend className='mb-2 text-sm font-medium'>
              How the team works
            </legend>
            <div className='grid gap-3 sm:grid-cols-2'>
              {(templates.data ?? []).map((t) => {
                const copy = TEMPLATE_COPY[t.slug]
                const Icon = copy?.icon ?? ListOrdered
                const on = chosen === t.id
                return (
                  <label
                    key={t.id}
                    className={cn(
                      'flex cursor-pointer gap-3 rounded-lg border bg-card p-4 has-focus-visible:ring-2 has-focus-visible:ring-ring',
                      on && 'border-primary ring-1 ring-primary'
                    )}
                  >
                    <input
                      type='radio'
                      name='template'
                      className='sr-only'
                      checked={on}
                      onChange={() => setTemplate(t.id)}
                    />
                    <Icon className='mt-0.5 size-5 shrink-0 text-brass' />
                    <span>
                      <span className='block font-medium'>{t.name}</span>
                      <span className='mt-1 block text-sm text-muted-foreground'>
                        {copy?.blurb ?? t.description}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
            <p className='mt-2 text-xs text-muted-foreground'>
              Both can be switched on later in project settings.
            </p>
          </fieldset>
          <div className='grid gap-1.5'>
            <Label htmlFor='project-name'>Name</Label>
            <Input
              id='project-name'
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={250}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='project-description'>Description</Label>
            <Textarea
              id='project-description'
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder='What the project is for, in a sentence or two.'
            />
          </div>
          <fieldset className='grid gap-2'>
            <legend className='mb-1 text-sm font-medium'>Who can see it</legend>
            {[
              [true, 'Private', 'Only members see the project.'],
              [
                false,
                'Public',
                'Anyone can view it and find it in Discover; only members can change it.',
              ],
            ].map(([value, label, hint]) => (
              <label
                key={String(value)}
                className='flex items-start gap-2 text-sm'
              >
                <input
                  type='radio'
                  name='privacy'
                  className='mt-1'
                  checked={isPrivate === value}
                  onChange={() => setPrivate(value as boolean)}
                />
                <span>
                  <span className='font-medium'>{label as string}</span>
                  <span className='block text-muted-foreground'>
                    {hint as string}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>
          <div>
            <Button
              type='submit'
              disabled={!name.trim() || !chosen || create.isPending}
            >
              {create.isPending && <Loader2 className='animate-spin' />}
              Create project
            </Button>
          </div>
        </form>
        <ImportDump />
        <ImporterLinks />
      </Main>
    </>
  )
}
