import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useFormat } from '@/i18n/format'
import { ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import type { HistoryChange, Id } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import { UserAvatar } from '@/components/user-avatar'

/** Who changed a wiki page and when, with each edit's diff. */
export function WikiHistory({ pageId }: { pageId: Id }) {
  const { t } = useTranslation(['pages', 'common'])
  const { timeAgo } = useFormat()
  const [open, setOpen] = useState(false)
  const history = useQuery({
    queryKey: ['wiki-history', pageId],
    enabled: open,
    queryFn: async () =>
      (await api.get<HistoryChange[]>(`/history/wiki/${pageId}`)).data,
  })
  const edits = (history.data ?? []).filter((e) => e.values_diff?.content_diff)

  return (
    <section className='mt-10 border-t pt-6'>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className='inline-flex items-center gap-1 text-sm font-semibold'
      >
        <ChevronRight
          className={cn('size-4 transition-transform', open && 'rotate-90')}
        />
        {t('wiki.history.title')}
      </button>
      {open &&
        (history.isPending ? (
          <Skeleton className='mt-3 h-16 w-full' />
        ) : edits.length === 0 ? (
          <p className='mt-3 text-sm text-muted-foreground'>
            {t('wiki.history.empty')}
          </p>
        ) : (
          <ol className='mt-3 grid gap-3'>
            {edits.map((e) => {
              const diff = (e.values_diff.content_diff as [unknown, string])[1]
              return (
                <li key={e.id} className='rounded-md border'>
                  <details>
                    <summary className='flex cursor-pointer items-center gap-2 px-3 py-2 text-sm'>
                      <UserAvatar
                        user={{
                          photo: e.user.photo,
                          full_name_display: e.user.name,
                        }}
                        className='size-5'
                      />
                      <span className='font-medium'>{e.user.name}</span>
                      <span className='text-muted-foreground'>
                        {t('wiki.history.edited', {
                          when: timeAgo(e.created_at),
                        })}
                      </span>
                    </summary>
                    {/* content_diff is built and escaped by kemudi-back. */}
                    <div
                      className='wiki-diff border-t px-3 py-2 text-sm whitespace-pre-wrap'
                      dangerouslySetInnerHTML={{ __html: diff }}
                    />
                  </details>
                </li>
              )
            })}
          </ol>
        ))}
    </section>
  )
}
