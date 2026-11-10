import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Merge, Plus, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useRefreshProject } from '@/lib/taiga/admin'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

function useTagAction(projectId: number, action: string) {
  const refresh = useRefreshProject()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.post(`/projects/${projectId}/${action}`, body),
    onError: onFail,
    onSettled: refresh,
  })
}

export function TagsSettings() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  const create = useTagAction(project.id, 'create_tag')
  const edit = useTagAction(project.id, 'edit_tag')
  const remove = useTagAction(project.id, 'delete_tag')
  const mix = useTagAction(project.id, 'mix_tags')

  const [name, setName] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [deleting, setDeleting] = useState<string | null>(null)
  const [mergeInto, setMergeInto] = useState('')
  const tags = Object.entries(project.tags_colors).sort(([a], [b]) =>
    a.localeCompare(b)
  )

  return (
    <div className='grid gap-6'>
      <SettingsSection
        title={t('common:terms.tags')}
        description={t('tags.description')}
      >
        {tags.length === 0 ? (
          <p className='text-sm text-muted-foreground'>{t('tags.empty')}</p>
        ) : (
          <ul className='grid gap-1.5'>
            {tags.map(([tag, color]) => (
              <li key={tag} className='flex items-center gap-2'>
                <Checkbox
                  aria-label={t('tags.selectToMerge', { tag })}
                  checked={selected.includes(tag)}
                  onCheckedChange={(v) =>
                    setSelected((s) =>
                      v ? [...s, tag] : s.filter((x) => x !== tag)
                    )
                  }
                />
                <input
                  type='color'
                  aria-label={t('shared.colourOf', { name: tag })}
                  defaultValue={color ?? '#A9AABC'}
                  onBlur={(e) =>
                    e.target.value !== color &&
                    edit.mutate({ from_tag: tag, color: e.target.value })
                  }
                  className='h-8 w-9 cursor-pointer rounded border bg-transparent'
                />
                <Input
                  aria-label={t('tags.nameOf', { tag })}
                  defaultValue={tag}
                  onBlur={(e) => {
                    const v = e.target.value.trim().toLowerCase()
                    if (v && v !== tag)
                      edit.mutate({ from_tag: tag, to_tag: v })
                  }}
                  onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                  className='h-8 w-56'
                />
                <Button
                  variant='ghost'
                  size='icon'
                  className='size-8 text-muted-foreground'
                  aria-label={t('shared.deleteNamed', { name: tag })}
                  onClick={() => setDeleting(tag)}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}
        {selected.length > 1 && (
          <div className='mt-4 flex flex-wrap items-center gap-2 rounded-md bg-muted p-3 text-sm'>
            <Merge className='size-4' />
            {t('tags.mergeCount', { count: selected.length })}
            <select
              aria-label={t('tags.mergeInto')}
              value={mergeInto || selected[0]}
              onChange={(e) => setMergeInto(e.target.value)}
              className='h-8 rounded-md border bg-background px-2'
            >
              {selected.map((tag) => (
                <option key={tag}>{tag}</option>
              ))}
            </select>
            <Button
              size='sm'
              onClick={() => {
                const to = mergeInto || selected[0]
                mix.mutate(
                  { from_tags: selected.filter((x) => x !== to), to_tag: to },
                  { onSuccess: () => setSelected([]) }
                )
              }}
            >
              {t('tags.merge')}
            </Button>
          </div>
        )}
        <form
          className='mt-4 flex gap-2'
          onSubmit={(e) => {
            e.preventDefault()
            const tag = name.trim().toLowerCase()
            if (!tag) return
            create.mutate(
              { tag, color: '#A9AABC' },
              { onSuccess: () => setName('') }
            )
          }}
        >
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('tags.new')}
            aria-label={t('tags.new')}
            className='h-8 w-56'
          />
          <Button size='sm' variant='outline' disabled={!name.trim()}>
            <Plus />
            {t('tags.add')}
          </Button>
        </form>
      </SettingsSection>
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={t('tags.deleteTitle', { tag: deleting ?? '' })}
        desc={t('tags.deleteDescription')}
        confirmText={t('tags.confirm')}
        destructive
        isLoading={remove.isPending}
        handleConfirm={() =>
          deleting &&
          remove.mutate(
            { tag: deleting },
            { onSuccess: () => setDeleting(null) }
          )
        }
      />
    </div>
  )
}
