import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from '@tanstack/react-router'
import { FolderKanban, Laptop, Moon, Sun } from 'lucide-react'
import { projectQuery, storiesQuery, useProjects } from '@/lib/taiga/queries'
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

/** Ctrl/Cmd+K: jump to a view, a project, or a story in the open project. */
export function CommandMenu() {
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
  const { data: stories = [] } = useQuery({
    ...storiesQuery(project?.id ?? 0),
    enabled: open && !!project,
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
      <CommandInput placeholder='Jump to a view, project or story' />
      <CommandList>
        <ScrollArea type='hover' className='h-80 pe-1'>
          <CommandEmpty>Nothing matches.</CommandEmpty>
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

          {project && stories.length > 0 && (
            <CommandGroup heading={`Stories in ${project.name}`}>
              {stories.map((story) => (
                <CommandItem
                  key={story.id}
                  value={`#${story.ref} ${story.subject}`}
                  onSelect={() =>
                    run(() =>
                      navigate({
                        to: '.',
                        search: (prev: Record<string, unknown>) => ({
                          ...prev,
                          story: story.ref,
                        }),
                      })
                    )
                  }
                >
                  <span className='w-10 shrink-0 text-xs text-muted-foreground tabular-nums'>
                    #{story.ref}
                  </span>
                  <span className='truncate'>{story.subject}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}

          {projects.length > 0 && (
            <CommandGroup heading='Projects'>
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
          <CommandGroup heading='Theme'>
            <CommandItem onSelect={() => run(() => setTheme('light'))}>
              <Sun /> Light
            </CommandItem>
            <CommandItem onSelect={() => run(() => setTheme('dark'))}>
              <Moon /> Dark
            </CommandItem>
            <CommandItem onSelect={() => run(() => setTheme('system'))}>
              <Laptop /> Match system
            </CommandItem>
          </CommandGroup>
        </ScrollArea>
      </CommandList>
    </CommandDialog>
  )
}
