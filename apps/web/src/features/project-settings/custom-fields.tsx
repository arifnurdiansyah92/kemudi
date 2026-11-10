import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { CustomAttribute, ItemKind, Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

const KIND_LABEL: [ItemKind, string][] = [
  ['epic', 'Epics'],
  ['userstory', 'Stories'],
  ['task', 'Tasks'],
  ['issue', 'Issues'],
]

const TYPES: [CustomAttribute['type'], string][] = [
  ['text', 'Short text'],
  ['multiline', 'Long text'],
  ['richtext', 'Formatted text'],
  ['number', 'Number'],
  ['date', 'Date'],
  ['url', 'Link'],
  ['checkbox', 'Checkbox'],
  ['dropdown', 'List of choices'],
]

export function CustomFieldsSettings() {
  const project = useProject()
  return (
    <div className='grid gap-6'>
      {KIND_LABEL.map(([kind, label]) => (
        <FieldList key={kind} project={project} kind={kind} label={label} />
      ))}
    </div>
  )
}

function useFields(project: Project, kind: ItemKind) {
  const qc = useQueryClient()
  const key = ['custom-attributes', kind, project.id]
  const base = `/${kind}-custom-attributes`
  const settle = () => qc.invalidateQueries({ queryKey: key })
  const list = useQuery({
    queryKey: key,
    queryFn: async () =>
      (
        await api.get<CustomAttribute[]>(`/${kind}-custom-attributes`, {
          params: { project: project.id },
        })
      ).data.sort((a, b) => a.order - b.order),
  })
  const create = useMutation({
    mutationFn: (input: Partial<CustomAttribute>) =>
      api.post(base, {
        project: project.id,
        order: (list.data?.length ?? 0) + 1,
        ...input,
      }),
    onError: onFail,
    onSettled: settle,
  })
  const update = useMutation({
    mutationFn: ({
      f,
      patch,
    }: {
      f: CustomAttribute
      patch: Partial<CustomAttribute>
    }) => api.patch(`${base}/${f.id}`, patch),
    onError: onFail,
    onSettled: settle,
  })
  const remove = useMutation({
    mutationFn: (f: CustomAttribute) => api.delete(`${base}/${f.id}`),
    onError: onFail,
    onSettled: settle,
  })
  const reorder = useMutation({
    mutationFn: (fields: CustomAttribute[]) =>
      Promise.all(
        fields.map((f, i) =>
          f.order === i + 1
            ? null
            : api.patch(`${base}/${f.id}`, { order: i + 1 })
        )
      ),
    onMutate: (fields) =>
      qc.setQueryData(
        key,
        fields.map((f, i) => ({ ...f, order: i + 1 }))
      ),
    onError: onFail,
    onSettled: settle,
  })
  return { list, create, update, remove, reorder }
}

function FieldList({
  project,
  kind,
  label,
}: {
  project: Project
  kind: ItemKind
  label: string
}) {
  const f = useFields(project, kind)
  const [name, setName] = useState('')
  const [type, setType] = useState<CustomAttribute['type']>('text')
  const [deleting, setDeleting] = useState<CustomAttribute | null>(null)
  const fields = f.list.data ?? []

  const move = (i: number, dir: -1 | 1) => {
    const next = [...fields]
    ;[next[i], next[i + dir]] = [next[i + dir], next[i]]
    f.reorder.mutate(next)
  }

  return (
    <SettingsSection
      title={label}
      description={`Extra fields on every ${label.toLowerCase().replace(/s$/, '').replace('storie', 'story')}.`}
    >
      {f.list.isPending ? (
        <Skeleton className='h-12 w-full' />
      ) : fields.length === 0 ? (
        <p className='text-sm text-muted-foreground'>No custom fields yet.</p>
      ) : (
        <ul className='grid gap-3'>
          {fields.map((field, i) => (
            <li
              key={`${field.id}-${field.order}`}
              className='grid gap-2 rounded-md border p-3'
            >
              <div className='flex flex-wrap items-center gap-2'>
                <span className='flex flex-col'>
                  <button
                    aria-label={`Move ${field.name} up`}
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                    className='text-muted-foreground hover:text-foreground disabled:opacity-30'
                  >
                    <ArrowUp className='size-3.5' />
                  </button>
                  <button
                    aria-label={`Move ${field.name} down`}
                    disabled={i === fields.length - 1}
                    onClick={() => move(i, 1)}
                    className='text-muted-foreground hover:text-foreground disabled:opacity-30'
                  >
                    <ArrowDown className='size-3.5' />
                  </button>
                </span>
                <Input
                  aria-label='Field name'
                  defaultValue={field.name}
                  onBlur={(e) => {
                    const v = e.target.value.trim()
                    if (v && v !== field.name)
                      f.update.mutate({ f: field, patch: { name: v } })
                  }}
                  className='h-8 w-48'
                />
                <select
                  aria-label={`Type of ${field.name}`}
                  value={field.type}
                  onChange={(e) =>
                    f.update.mutate({
                      f: field,
                      patch: {
                        type: e.target.value as CustomAttribute['type'],
                      },
                    })
                  }
                  className='h-8 rounded-md border bg-transparent px-2 text-sm'
                >
                  {TYPES.map(([t, l]) => (
                    <option key={t} value={t}>
                      {l}
                    </option>
                  ))}
                </select>
                <Input
                  aria-label={`Help text for ${field.name}`}
                  placeholder='Help text (optional)'
                  defaultValue={field.description}
                  onBlur={(e) =>
                    e.target.value !== field.description &&
                    f.update.mutate({
                      f: field,
                      patch: { description: e.target.value },
                    })
                  }
                  className='h-8 min-w-40 flex-1'
                />
                <Button
                  variant='ghost'
                  size='icon'
                  className='size-8 text-muted-foreground'
                  aria-label={`Delete ${field.name}`}
                  onClick={() => setDeleting(field)}
                >
                  <Trash2 />
                </Button>
              </div>
              {field.type === 'dropdown' && (
                <Input
                  aria-label={`Choices for ${field.name}`}
                  placeholder='Choices, separated by commas'
                  defaultValue={(field.extra ?? []).join(', ')}
                  onBlur={(e) => {
                    const extra = e.target.value
                      .split(',')
                      .map((x) => x.trim())
                      .filter(Boolean)
                    f.update.mutate({ f: field, patch: { extra } })
                  }}
                  className='h-8'
                />
              )}
            </li>
          ))}
        </ul>
      )}
      <form
        className='mt-3 flex flex-wrap gap-2'
        onSubmit={(e) => {
          e.preventDefault()
          if (!name.trim()) return
          f.create.mutate(
            {
              name: name.trim(),
              type,
              description: '',
              ...(type === 'dropdown' ? { extra: [] } : {}),
            },
            { onSuccess: () => setName('') }
          )
        }}
      >
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder='New field name'
          aria-label={`New ${label.toLowerCase()} field`}
          className='h-8 w-56'
        />
        <select
          aria-label='New field type'
          value={type}
          onChange={(e) => setType(e.target.value as CustomAttribute['type'])}
          className='h-8 rounded-md border bg-transparent px-2 text-sm'
        >
          {TYPES.map(([t, l]) => (
            <option key={t} value={t}>
              {l}
            </option>
          ))}
        </select>
        <Button size='sm' variant='outline' disabled={!name.trim()}>
          <Plus />
          Add field
        </Button>
      </form>
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete the ${deleting?.name ?? ''} field?`}
        desc='Its values are deleted from every item.'
        confirmText='Delete field'
        destructive
        isLoading={f.remove.isPending}
        handleConfirm={() =>
          deleting &&
          f.remove.mutate(deleting, { onSuccess: () => setDeleting(null) })
        }
      />
    </SettingsSection>
  )
}
