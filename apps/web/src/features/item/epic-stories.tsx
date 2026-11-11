import { useState } from 'react'
import { Link2, Plus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useEpicLinks, useEpicStories, useEpics } from '@/lib/taiga/epics'
import { useStories } from '@/lib/taiga/queries'
import type { Item, Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Skeleton } from '@/components/ui/skeleton'
import { can, useRefParam } from '@/features/project/use-project'
import { StatusDot } from '@/features/story/parts'

/** The stories under an epic: open, unlink, link existing, or add new ones. */
export function EpicStories({
  project,
  epic,
}: {
  project: Project
  epic: Item
}) {
  const { t } = useTranslation('item')
  const stories = useEpicStories(project.id, epic.id)
  const all = useStories(project.id)
  const { link, unlink, create } = useEpicLinks(project)
  const { open } = useRefParam()
  const [picking, setPicking] = useState(false)
  const [subject, setSubject] = useState('')
  const editable = can(project, 'modify_epic')

  if (stories.isPending) return <Skeleton className='h-16 w-full' />
  const list = stories.data ?? []
  const linked = new Set(list.map((s) => s.id))
  const done = list.filter((s) => s.is_closed).length

  return (
    <div className='grid gap-2'>
      {list.length > 0 && (
        <>
          <p className='text-xs text-muted-foreground tabular-nums'>
            {t('epic.progress', { done, count: list.length })}
          </p>
          <ul className='grid gap-0.5'>
            {list.map((story) => (
              <li
                key={story.id}
                className='group flex items-center gap-3 rounded-md px-1 py-1.5 text-sm hover:bg-accent/50'
              >
                <span className='w-9 shrink-0 text-xs text-muted-foreground tabular-nums'>
                  #{story.ref}
                </span>
                <button
                  onClick={() => open(story.ref)}
                  className={cn(
                    'min-w-0 flex-1 truncate text-start hover:underline hover:underline-offset-4',
                    story.is_closed && 'text-muted-foreground line-through'
                  )}
                >
                  {story.subject}
                </button>
                <span className='inline-flex items-center gap-1.5 text-xs text-muted-foreground'>
                  <StatusDot color={story.status_extra_info.color} />
                  {story.status_extra_info.name}
                </span>
                {editable && (
                  <Button
                    variant='ghost'
                    size='icon'
                    className='size-6 text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100'
                    aria-label={t('epic.removeStory', { ref: story.ref })}
                    onClick={() =>
                      unlink.mutate({ epicId: epic.id, storyId: story.id })
                    }
                  >
                    <X />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {list.length === 0 && (
        <p className='text-sm text-muted-foreground'>{t('epic.noStories')}</p>
      )}

      {editable && (
        <div className='flex flex-wrap items-center gap-2'>
          <form
            className='min-w-48 flex-1'
            onSubmit={(e) => {
              e.preventDefault()
              const text = subject.trim()
              if (!text) return
              create.mutate({ epicId: epic.id, text })
              setSubject('')
            }}
          >
            <label className='flex h-9 items-center gap-2 rounded-md border border-dashed px-3 text-sm focus-within:border-solid focus-within:ring-2 focus-within:ring-ring'>
              <Plus
                className='size-4 text-muted-foreground'
                aria-hidden='true'
              />
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder={t('epic.newStory')}
                aria-label={t('epic.newStory')}
                className='min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground'
              />
            </label>
          </form>
          <Popover open={picking} onOpenChange={setPicking}>
            <PopoverTrigger asChild>
              <Button variant='outline' size='sm' className='h-9'>
                <Link2 />
                {t('epic.linkStory')}
              </Button>
            </PopoverTrigger>
            <PopoverContent className='w-80 p-0' align='end'>
              <Command>
                <CommandInput placeholder={t('epic.findStory')} />
                <CommandList>
                  <CommandEmpty>{t('epic.noStoryMatches')}</CommandEmpty>
                  <CommandGroup>
                    {(all.data ?? [])
                      .filter((s) => !linked.has(s.id))
                      .map((s) => (
                        <CommandItem
                          key={s.id}
                          value={`#${s.ref} ${s.subject}`}
                          onSelect={() => {
                            link.mutate({ epicId: epic.id, storyId: s.id })
                            setPicking(false)
                          }}
                        >
                          <span className='w-9 shrink-0 text-xs text-muted-foreground tabular-nums'>
                            #{s.ref}
                          </span>
                          <span className='truncate'>{s.subject}</span>
                        </CommandItem>
                      ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </div>
      )}
    </div>
  )
}

/** On a story: its epics as chips, with a picker to add one. */
export function StoryEpics({
  project,
  story,
}: {
  project: Project
  story: Item
}) {
  const { t } = useTranslation(['item', 'common'])
  const epics = useEpics(project.id)
  const { link, unlink } = useEpicLinks(project)
  const { open } = useRefParam()
  const [picking, setPicking] = useState(false)
  const current = story.epics ?? []
  const editable = can(project, 'modify_us')

  return (
    <div className='flex flex-wrap items-center gap-1.5'>
      {current.map((epic) => (
        <span
          key={epic.id}
          className='inline-flex h-6 items-center gap-1.5 rounded-sm border ps-1.5 pe-1 text-xs'
        >
          <span
            aria-hidden='true'
            className='size-2 rounded-full'
            style={{ backgroundColor: epic.color }}
          />
          <button onClick={() => open(epic.ref)} className='hover:underline'>
            #{epic.ref} {epic.subject}
          </button>
          {editable && (
            <button
              aria-label={t('epic.removeFromEpic', { ref: epic.ref })}
              className='text-muted-foreground hover:text-foreground'
              onClick={() =>
                unlink.mutate({ epicId: epic.id, storyId: story.id })
              }
            >
              <X className='size-3' />
            </button>
          )}
        </span>
      ))}
      {editable && (
        <Popover open={picking} onOpenChange={setPicking}>
          <PopoverTrigger className='inline-flex h-6 items-center gap-1 rounded-sm border border-dashed px-1.5 text-xs text-muted-foreground hover:bg-accent'>
            <Plus className='size-3' />
            {t('epic.addToEpic')}
          </PopoverTrigger>
          <PopoverContent className='w-72 p-0' align='start'>
            <Command>
              <CommandInput placeholder={t('epic.findEpic')} />
              <CommandList>
                <CommandEmpty>{t('epic.noEpicMatches')}</CommandEmpty>
                <CommandGroup>
                  {(epics.data ?? [])
                    .filter((e) => !current.some((c) => c.id === e.id))
                    .map((e) => (
                      <CommandItem
                        key={e.id}
                        value={`#${e.ref} ${e.subject}`}
                        onSelect={() => {
                          link.mutate({ epicId: e.id, storyId: story.id })
                          setPicking(false)
                        }}
                      >
                        <span
                          aria-hidden='true'
                          className='size-2 rounded-full'
                          style={{ backgroundColor: e.color }}
                        />
                        <span className='truncate'>
                          #{e.ref} {e.subject}
                        </span>
                      </CommandItem>
                    ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      )}
      {!editable && current.length === 0 && (
        <span className='text-sm text-muted-foreground'>
          {t('common:status.none')}
        </span>
      )}
    </div>
  )
}
