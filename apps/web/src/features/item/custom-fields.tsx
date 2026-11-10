import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useCustomAttributes,
  useCustomValues,
  useUpdateCustomValues,
} from '@/lib/taiga/items'
import type {
  CustomAttribute,
  Item,
  ItemKind,
  Project,
} from '@/lib/taiga/types'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

type Value = string | number | boolean | null

/**
 * The project's custom fields for this item kind. Renders nothing when the
 * project defines none.
 */
export function CustomFields({
  project,
  kind,
  item,
  editable,
}: {
  project: Project
  kind: ItemKind
  item: Item
  editable: boolean
}) {
  const { t } = useTranslation('item')
  const attributes = useCustomAttributes(project, kind)
  const hasAttributes = (attributes.data?.length ?? 0) > 0
  const values = useCustomValues(kind, item.id, hasAttributes)
  const update = useUpdateCustomValues(kind, item.id)

  if (!hasAttributes || !values.data) return null
  const current = values.data.attributes_values

  const save = (id: number, value: Value) =>
    update.mutate({ ...current, [id]: value })

  return (
    <section className='border-t px-6 py-5'>
      <h3 className='mb-3 text-sm font-semibold'>{t('customFields.title')}</h3>
      <dl className='grid grid-cols-[minmax(7rem,max-content)_1fr] items-start gap-x-4 gap-y-3 text-sm'>
        {attributes.data!.map((attr) => (
          <div key={attr.id} className='contents'>
            <dt
              className='pt-1.5 text-muted-foreground'
              title={attr.description}
            >
              {attr.name}
            </dt>
            <dd>
              <CustomInput
                attr={attr}
                value={current[attr.id] ?? null}
                editable={editable}
                onSave={(v) => save(attr.id, v)}
              />
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function CustomInput({
  attr,
  value,
  editable,
  onSave,
}: {
  attr: CustomAttribute
  value: Value
  editable: boolean
  onSave: (v: Value) => void
}) {
  const { t } = useTranslation('item')
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  const commit = () => {
    const next =
      attr.type === 'number' ? (draft === '' ? null : Number(draft)) : draft
    if (next !== value) onSave(next)
  }

  if (attr.type === 'checkbox')
    return (
      <Checkbox
        aria-label={attr.name}
        checked={value === true}
        disabled={!editable}
        onCheckedChange={(v) => onSave(v === true)}
        className='mt-1.5'
      />
    )

  if (!editable)
    return attr.type === 'url' && value ? (
      <a
        href={String(value)}
        target='_blank'
        rel='noreferrer'
        className='block pt-1.5 underline underline-offset-4'
      >
        {String(value)}
      </a>
    ) : (
      <span className='block pt-1.5 whitespace-pre-wrap'>
        {value === null || value === '' ? (
          <span className='text-muted-foreground'>
            {t('customFields.empty')}
          </span>
        ) : (
          String(value)
        )}
      </span>
    )

  if (attr.type === 'dropdown')
    return (
      <select
        aria-label={attr.name}
        value={value === null ? '' : String(value)}
        onChange={(e) => onSave(e.target.value || null)}
        className='h-8 w-full rounded-md border bg-transparent px-2 text-sm'
      >
        <option value=''>{t('customFields.empty')}</option>
        {(attr.extra ?? []).map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    )

  if (attr.type === 'multiline' || attr.type === 'richtext')
    return (
      <Textarea
        aria-label={attr.name}
        value={draft}
        rows={3}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
      />
    )

  return (
    <Input
      aria-label={attr.name}
      type={
        attr.type === 'date'
          ? 'date'
          : attr.type === 'number'
            ? 'number'
            : attr.type === 'url'
              ? 'url'
              : 'text'
      }
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      className='h-8'
    />
  )
}
