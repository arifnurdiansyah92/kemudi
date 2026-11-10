import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from '@tanstack/react-router'
import { FolderKanban, Laptop, Moon, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { api } from '@/lib/taiga/client'
import { projectQuery, useProjects } from '@/lib/taiga/queries'
import { useSearch } from '@/context/search-provider'
import { useTheme } from '@/context/theme-provider'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { useNavGroups } from './layout/use-nav-groups'
import { ScrollArea } from './ui/scroll-area'

type Hit = { id: number; ref?: number; subject?: string; slug?: string }
type SearchResults = Record<
  'userstories' | 'tasks' | 'issues' | 'epics' | 'wikipages',
  Hit[]
>
const SEARCH_GROUPS = [
  'userstories',
  'tasks',
  'issues',
  'epics',
  'wikipages',
] as const satisfies (keyof SearchResults)[]

/**
 * Ctrl/Cmd+K: jump to a view or project, or search the open project's
 * stories, tasks, issues, epics and wiki (server-side, two letters or more).
 */
export function CommandMenu() {
  const { t } = useTranslation(['shell', 'common'])
  const navigate = useNavigate()
  const { setTheme } = useTheme()
  const { open, setOpen } = useSearch()
  const groups = useNavGroups()
  const { data: projects = [] } = useProjects()
  const { slug } = useParams({ strict: false }) as { slug?: string }
  const { data: project } = useQuery({
    ...projectQuery(slug ?? ''),
    enabled: !!slug,
  })
  const [query, setQuery] = React.useState('')
  const [debounced, setDebounced] = React.useState('')
  React.useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(query.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [query])
  const { data: results } = useQuery({
    queryKey: ['search', project?.id, debounced],
    enabled: open && !!project && debounced.length >= 2,
    queryFn: async () =>
      (
        await api.get<SearchResults>('/search', {
          params: { project: project!.id, text: debounced },
        })
      ).data,
  })

  const run = React.useCallback(
    (command: () => unknown) => {
      setOpen(false)
      command()
    },
    [setOpen]
  )

  return (
    <CommandDialog modal open={open} onOpenChange={setOpen}>
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder={
          project
            ? t('commandMenu.placeholderProject', { project: project.name })
            : t('commandMenu.placeholder')
        }
      />
      <CommandList>
        <ScrollArea type='hover' className='h-80 pe-1'>
          <CommandEmpty>{t('commandMenu.empty')}</CommandEmpty>
          {groups.map((group) => (
            <CommandGroup key={group.title} heading={group.title}>
              {group.items.map(
                (item) =>
                  item.url && (
                    <CommandItem
                      key={item.url}
                      value={`${group.title} ${item.title}`}
                      onSelect={() =>
                        run(() => navigate({ to: item.url as string }))
                      }
                    >
                      {item.icon && <item.icon />}
                      {item.title}
                    </CommandItem>
                  )
              )}
            </CommandGroup>
          ))}

          {project &&
            results &&
            SEARCH_GROUPS.map((key) => {
              const hits = results[key]
              if (!hits?.length) return null
              return (
                <CommandGroup
                  key={key}
                  heading={t(`commandMenu.resultsIn.${key}`, {
                    project: project.name,
                  })}
                >
                  {hits.map((hit) => (
                    <CommandItem
                      key={`${key}-${hit.id}`}
                      // Results are already matched by the server; keep the
                      // query in the value so cmdk does not hide them.
                      value={`${query} ${key} ${hit.ref ?? hit.slug} ${hit.subject ?? hit.slug}`}
                      onSelect={() =>
                        run(() =>
                          key === 'wikipages'
                            ? navigate({
                                to: '/p/$slug/wiki/$page',
                                params: { slug: project.slug, page: hit.slug! },
                              })
                            : navigate({
                                to: '.',
                                search: (prev: Record<string, unknown>) => ({
                                  ...prev,
                                  ref: hit.ref,
                                }),
                              })
                        )
                      }
                    >
                      {hit.ref && (
                        <span className='w-10 shrink-0 text-xs text-muted-foreground tabular-nums'>
                          #{hit.ref}
                        </span>
                      )}
                      <span className='truncate'>
                        {hit.subject ?? hit.slug}
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              )
            })}

          {projects.length > 0 && (
            <CommandGroup heading={t('common:terms.project_other')}>
              {projects.map((p) => (
                <CommandItem
                  key={p.id}
                  value={`project ${p.name}`}
                  onSelect={() =>
                    run(() =>
                      navigate({ to: '/p/$slug', params: { slug: p.slug } })
                    )
                  }
                >
                  <FolderKanban />
                  {p.name}
                </CommandItem>
              ))}
            </CommandGroup>
          )}

          <CommandSeparator />
          <CommandGroup heading={t('theme.label')}>
            <CommandItem onSelect={() => run(() => setTheme('light'))}>
              <Sun /> {t('theme.light')}
            </CommandItem>
            <CommandItem onSelect={() => run(() => setTheme('dark'))}>
              <Moon /> {t('theme.dark')}
            </CommandItem>
            <CommandItem onSelect={() => run(() => setTheme('system'))}>
              <Laptop /> {t('theme.matchSystem')}
            </CommandItem>
          </CommandGroup>
        </ScrollArea>
      </CommandList>
    </CommandDialog>
  )
}
