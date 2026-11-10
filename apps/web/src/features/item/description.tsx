import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useUpdateItem } from '@/lib/taiga/items'
import type { Item, ItemKind, Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { MentionTextarea } from '@/components/mention-textarea'

export function Description({
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
  const { t } = useTranslation(['item', 'common'])
  const update = useUpdateItem(project, kind)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(item.description ?? '')

  const start = () => {
    setValue(item.description ?? '')
    setEditing(true)
  }

  if (editing)
    return (
      <form
        className='grid gap-2'
        onSubmit={(e) => {
          e.preventDefault()
          update.mutate(
            { item, patch: { description: value } },
            { onSuccess: () => setEditing(false) }
          )
        }}
      >
        <MentionTextarea
          project={project}
          value={value}
          onChange={setValue}
          rows={8}
          autoFocus
          aria-label={t('common:terms.description')}
          placeholder={t('description.placeholder')}
        />
        <div className='flex gap-2'>
          <Button size='sm' type='submit' disabled={update.isPending}>
            {update.isPending && <Loader2 className='animate-spin' />}
            {t('description.save')}
          </Button>
          <Button
            size='sm'
            variant='ghost'
            type='button'
            onClick={() => setEditing(false)}
          >
            {t('common:actions.cancel')}
          </Button>
        </div>
      </form>
    )

  if (!item.description)
    return editable ? (
      <button
        onClick={start}
        className='w-full rounded-md border border-dashed px-3 py-4 text-start text-sm text-muted-foreground hover:bg-accent/50'
      >
        {t('description.add')}
      </button>
    ) : (
      <p className='text-sm text-muted-foreground'>{t('description.empty')}</p>
    )

  return (
    <div>
      {/* description_html is rendered and sanitised by kemudi-back (bleach). */}
      <div
        className='rich-text text-sm'
        dangerouslySetInnerHTML={{ __html: item.description_html ?? '' }}
      />
      {editable && (
        <Button size='sm' variant='outline' className='mt-3' onClick={start}>
          {t('description.edit')}
        </Button>
      )}
    </div>
  )
}
