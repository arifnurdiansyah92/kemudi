import { useState } from 'react'
import { AxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bookmark, Check, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { isFiltering, type FilterState } from './apply'

type Saved = Record<string, FilterState>

/**
 * Named filter sets per user, kept on the server in user storage so they
 * follow the user across devices.
 */
function useSavedFilters(storageKey: string) {
  const qc = useQueryClient()
  const key = ['user-storage', storageKey]
  const list = useQuery({
    queryKey: key,
    queryFn: async (): Promise<{ exists: boolean; value: Saved }> => {
      try {
        const { data } = await api.get<{ value: Saved }>(
          `/user-storage/${storageKey}`
        )
        return { exists: true, value: data.value ?? {} }
      } catch (e) {
        if (e instanceof AxiosError && e.response?.status === 404)
          return { exists: false, value: {} }
        throw e
      }
    },
  })
  const write = useMutation({
    // PUT once the entry exists on the server, POST to create it.
    mutationFn: (value: Saved) =>
      list.data?.exists
        ? api.put(`/user-storage/${storageKey}`, { key: storageKey, value })
        : api.post('/user-storage', { key: storageKey, value }),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  })
  return { saved: list.data?.value ?? {}, write }
}

export function SavedFilters({
  storageKey,
  value,
  onApply,
}: {
  storageKey: string
  value: FilterState
  onApply: (f: FilterState) => void
}) {
  const { t } = useTranslation(['board', 'common'])
  const { saved, write } = useSavedFilters(storageKey)
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')
  const names = Object.keys(saved).sort()
  const same = (a: FilterState, b: FilterState) =>
    JSON.stringify(a) === JSON.stringify(b)

  if (naming)
    return (
      <form
        className='flex items-center gap-1'
        onSubmit={(e) => {
          e.preventDefault()
          const n = name.trim()
          if (!n) return
          write.mutate({ ...saved, [n]: value })
          setName('')
          setNaming(false)
        }}
      >
        <Input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Escape' && setNaming(false)}
          placeholder={t('filters.saved.namePlaceholder')}
          aria-label={t('filters.saved.nameLabel')}
          className='h-8 w-44'
        />
        <Button size='sm' className='h-8' disabled={!name.trim()}>
          {t('common:actions.save')}
        </Button>
      </form>
    )

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button variant='ghost' size='sm' className='h-8'>
          <Bookmark />
          {t('filters.saved.button')}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align='start' className='min-w-56'>
        {names.length === 0 && (
          <DropdownMenuLabel className='text-xs font-normal text-muted-foreground'>
            {t('filters.saved.empty')}
          </DropdownMenuLabel>
        )}
        {names.map((n) => (
          <DropdownMenuItem key={n} onSelect={() => onApply(saved[n])}>
            {same(saved[n], value) ? <Check /> : <span className='size-4' />}
            <span className='truncate'>{n}</span>
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={!isFiltering(value)}
          onSelect={() => setNaming(true)}
        >
          {t('filters.saved.saveCurrent')}
        </DropdownMenuItem>
        {names.length > 0 && (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              {t('filters.saved.delete')}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {names.map((n) => (
                <DropdownMenuItem
                  key={n}
                  variant='destructive'
                  onSelect={() => {
                    const rest = { ...saved }
                    delete rest[n]
                    write.mutate(rest)
                  }}
                >
                  <X />
                  {n}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
