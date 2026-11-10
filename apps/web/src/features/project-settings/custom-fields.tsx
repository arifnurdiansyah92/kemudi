import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { CustomAttribute, ItemKind, Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

/** Item kinds with custom fields, and their list name in the common namespace. */
const KIND_LABEL = [
  ['epic', 'common:terms.epic_other'],
  ['userstory', 'common:terms.story_other'],
  ['task', 'common:terms.task_other'],
  ['issue', 'common:terms.issue_other'],
] as const satisfies readonly (readonly [ItemKind, string])[]

type FieldKind = (typeof KIND_LABEL)[number][0]

/** Field types; each label is customFields.types.<type> in the admin namespace. */
const TYPES = [
  'text',
  'multiline',
  'richtext',
  'number',
  'date',
  'url',
  'checkbox',
  'dropdown',
] as const satisfies readonly CustomAttribute['type'][]

export function CustomFieldsSettings() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  return (
    <div className='grid gap-6'>
      {KIND_LABEL.map(([kind, label]) => (
        <FieldList key={kind} project={project} kind={kind} label={t(label)} />
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
  kind: FieldKind
  label: string
}) {
  const { t } = useTranslation(['admin', 'common'])
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
      description={t(`customFields.kinds.${kind}.description`)}
    >
      {f.list.isPending ? (
        <Skeleton className='h-12 w-full' />
      ) : fields.length === 0 ? (
        <p className='text-sm text-muted-foreground'>
          {t('customFields.empty')}
        </p>
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
                    aria-label={t('shared.moveUp', { name: field.name })}
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                    className='text-muted-foreground hover:text-foreground disabled:opacity-30'
                  >
                    <ArrowUp className='size-3.5' />
                  </button>
                  <button
                    aria-label={t('shared.moveDown', { name: field.name })}
                    disabled={i === fields.length - 1}
                    onClick={() => move(i, 1)}
                    className='text-muted-foreground hover:text-foreground disabled:opacity-30'
                  >
                    <ArrowDown className='size-3.5' />
                  </button>
                </span>
                <Input
                  aria-label={t('customFields.fieldName')}
                  defaultValue={field.name}
                  onBlur={(e) => {
                    const v = e.target.value.trim()
                    if (v && v !== field.name)
                      f.update.mutate({ f: field, patch: { name: v } })
                  }}
                  className='h-8 w-48'
                />
                <select
                  aria-label={t('customFields.typeOf', { name: field.name })}
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
                  {TYPES.map((type) => (
                    <option key={type} value={type}>
                      {t(`customFields.types.${type}`)}
                    </option>
                  ))}
                </select>
                <Input
                  aria-label={t('customFields.helpTextFor', {
                    name: field.name,
                  })}
                  placeholder={t('customFields.helpText')}
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
                  aria-label={t('shared.deleteNamed', { name: field.name })}
                  onClick={() => setDeleting(field)}
                >
                  <Trash2 />
                </Button>
              </div>
              {field.type === 'dropdown' && (
                <Input
                  aria-label={t('customFields.choicesFor', {
                    name: field.name,
                  })}
                  placeholder={t('customFields.choices')}
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
          placeholder={t('customFields.newName')}
          aria-label={t(`customFields.kinds.${kind}.new`)}
          className='h-8 w-56'
        />
        <select
          aria-label={t('customFields.newType')}
          value={type}
          onChange={(e) => setType(e.target.value as CustomAttribute['type'])}
          className='h-8 rounded-md border bg-transparent px-2 text-sm'
        >
          {TYPES.map((type) => (
            <option key={type} value={type}>
              {t(`customFields.types.${type}`)}
            </option>
          ))}
        </select>
        <Button size='sm' variant='outline' disabled={!name.trim()}>
          <Plus />
          {t('customFields.add')}
        </Button>
      </form>
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t('customFields.deleteTitle', { name: deleting?.name ?? '' })}
        desc={t('customFields.deleteDescription')}
        confirmText={t('customFields.confirm')}
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
