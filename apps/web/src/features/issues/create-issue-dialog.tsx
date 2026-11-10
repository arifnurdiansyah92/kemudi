import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useBulkCreateIssues,
  useCreateIssue,
  type NewIssue,
} from '@/lib/taiga/issues'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'

function Select({
  id,
  label,
  value,
  onChange,
  options,
  empty,
}: {
  id: string
  label: string
  value: number | null | undefined
  onChange: (v: number | null) => void
  options: { id: number; name: string }[]
  empty?: string
}) {
  return (
    <div className='grid gap-1.5'>
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value ?? ''}
        onChange={(e) =>
          onChange(e.target.value ? Number(e.target.value) : null)
        }
        className='h-9 rounded-md border bg-transparent px-2 text-sm'
      >
        {empty && <option value=''>{empty}</option>}
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
    </div>
  )
}

export function CreateIssueDialog({
  project,
  open,
  onOpenChange,
  onCreated,
}: {
  project: Project
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (ref: number) => void
}) {
  const { t } = useTranslation(['board', 'common'])
  const create = useCreateIssue(project)
  const bulk = useBulkCreateIssues(project)
  const [form, setForm] = useState<NewIssue>(() => ({
    subject: '',
    description: '',
    type: project.default_issue_type,
    severity: project.default_severity,
    priority: project.default_priority,
    assigned_to: null,
  }))
  const [lines, setLines] = useState('')
  const sorted = <T extends { order: number }>(list: T[]) =>
    [...list].sort((a, b) => a.order - b.order)
  const count = lines.split('\n').filter((l) => l.trim()).length

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className='sm:max-w-lg'>
        <DialogHeader>
          <DialogTitle>{t('issues.create.title')}</DialogTitle>
          <DialogDescription>
            {t('issues.create.description')}
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue='one'>
          <TabsList>
            <TabsTrigger value='one'>{t('issues.create.tabOne')}</TabsTrigger>
            <TabsTrigger value='many'>{t('issues.create.tabMany')}</TabsTrigger>
          </TabsList>
          <TabsContent value='one'>
            <form
              className='mt-3 grid gap-4'
              onSubmit={(e) => {
                e.preventDefault()
                if (!form.subject.trim()) return
                create.mutate(
                  { ...form, subject: form.subject.trim() },
                  {
                    onSuccess: (issue) => {
                      onOpenChange(false)
                      onCreated(issue.ref)
                    },
                  }
                )
              }}
            >
              <div className='grid gap-1.5'>
                <Label htmlFor='issue-subject'>
                  {t('issues.create.subject')}
                </Label>
                <Input
                  id='issue-subject'
                  autoFocus
                  value={form.subject}
                  onChange={(e) =>
                    setForm({ ...form, subject: e.target.value })
                  }
                />
              </div>
              <div className='grid grid-cols-3 gap-3'>
                <Select
                  id='issue-type'
                  label={t('common:terms.type')}
                  value={form.type}
                  onChange={(type) => setForm({ ...form, type })}
                  options={sorted(project.issue_types)}
                />
                <Select
                  id='issue-severity'
                  label={t('common:terms.severity')}
                  value={form.severity}
                  onChange={(severity) => setForm({ ...form, severity })}
                  options={sorted(project.severities)}
                />
                <Select
                  id='issue-priority'
                  label={t('common:terms.priority')}
                  value={form.priority}
                  onChange={(priority) => setForm({ ...form, priority })}
                  options={sorted(project.priorities)}
                />
              </div>
              <Select
                id='issue-assignee'
                label={t('common:terms.assignee')}
                value={form.assigned_to}
                onChange={(assigned_to) => setForm({ ...form, assigned_to })}
                options={project.members
                  .filter((m) => m.is_active)
                  .map((m) => ({ id: m.id, name: m.full_name_display }))}
                empty={t('common:status.unassigned')}
              />
              <div className='grid gap-1.5'>
                <Label htmlFor='issue-description'>
                  {t('common:terms.description')}
                </Label>
                <Textarea
                  id='issue-description'
                  rows={5}
                  value={form.description}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                  placeholder={t('issues.create.descriptionPlaceholder')}
                />
              </div>
              <DialogFooter>
                <Button
                  type='submit'
                  disabled={!form.subject.trim() || create.isPending}
                >
                  {create.isPending && <Loader2 className='animate-spin' />}
                  {t('issues.create.submit')}
                </Button>
              </DialogFooter>
            </form>
          </TabsContent>
          <TabsContent value='many'>
            <form
              className='mt-3 grid gap-4'
              onSubmit={(e) => {
                e.preventDefault()
                if (!count) return
                bulk.mutate(lines, {
                  onSuccess: () => {
                    setLines('')
                    onOpenChange(false)
                  },
                })
              }}
            >
              <Textarea
                rows={8}
                value={lines}
                onChange={(e) => setLines(e.target.value)}
                aria-label={t('issues.create.bulkLabel')}
                placeholder={t('issues.create.bulkPlaceholder')}
              />
              <p className='text-xs text-muted-foreground'>
                {t('issues.create.bulkHelp')}
              </p>
              <DialogFooter>
                <Button type='submit' disabled={!count || bulk.isPending}>
                  {bulk.isPending && <Loader2 className='animate-spin' />}
                  {count > 1
                    ? t('issues.create.submitMany', { count })
                    : t('issues.create.submit')}
                </Button>
              </DialogFooter>
            </form>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
