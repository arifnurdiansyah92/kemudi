import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Columns3, ListOrdered, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
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
  {
    icon: React.ElementType
    blurb: 'projects.new.templates.scrum' | 'projects.new.templates.kanban'
  }
> = {
  scrum: { icon: ListOrdered, blurb: 'projects.new.templates.scrum' },
  kanban: { icon: Columns3, blurb: 'projects.new.templates.kanban' },
}

export function NewProject() {
  const { t } = useTranslation(['home', 'common'])
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
          { label: t('common:terms.project_other'), to: '/projects' },
          { label: t('projects.newProject') },
        ]}
      />
      <Main className='max-w-2xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('projects.newProject')}
        </h1>
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
              {t('projects.new.templateLegend')}
            </legend>
            <div className='grid gap-3 sm:grid-cols-2'>
              {(templates.data ?? []).map((tpl) => {
                const copy = TEMPLATE_COPY[tpl.slug]
                const Icon = copy?.icon ?? ListOrdered
                const on = chosen === tpl.id
                return (
                  <label
                    key={tpl.id}
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
                      onChange={() => setTemplate(tpl.id)}
                    />
                    <Icon className='mt-0.5 size-5 shrink-0 text-brass' />
                    <span>
                      <span className='block font-medium'>{tpl.name}</span>
                      <span className='mt-1 block text-sm text-muted-foreground'>
                        {copy ? t(copy.blurb) : tpl.description}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
            <p className='mt-2 text-xs text-muted-foreground'>
              {t('projects.new.templatesLater')}
            </p>
          </fieldset>
          <div className='grid gap-1.5'>
            <Label htmlFor='project-name'>{t('projects.new.name')}</Label>
            <Input
              id='project-name'
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={250}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='project-description'>
              {t('common:terms.description')}
            </Label>
            <Textarea
              id='project-description'
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('projects.new.descriptionPlaceholder')}
            />
          </div>
          <fieldset className='grid gap-2'>
            <legend className='mb-1 text-sm font-medium'>
              {t('projects.new.visibility')}
            </legend>
            {[
              [true, t('projects.new.private'), t('projects.new.privateHint')],
              [false, t('projects.new.public'), t('projects.new.publicHint')],
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
              {t('projects.new.submit')}
            </Button>
          </div>
        </form>
        <ImportDump />
        <ImporterLinks />
      </Main>
    </>
  )
}
