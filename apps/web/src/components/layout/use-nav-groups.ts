import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import {
  Bug,
  Layers,
  Columns3,
  FolderKanban,
  LayoutGrid,
  ListOrdered,
  Palette,
} from 'lucide-react'
import { projectQuery } from '@/lib/taiga/queries'
import { type NavGroup } from './types'

/** Sidebar groups: the workspace, then the open project's views. */
export function useNavGroups(): NavGroup[] {
  const { slug } = useParams({ strict: false }) as { slug?: string }
  const { data: project } = useQuery({
    ...projectQuery(slug ?? ''),
    enabled: !!slug,
  })

  const groups: NavGroup[] = [
    {
      title: 'Workspace',
      items: [{ title: 'Projects', url: '/', icon: FolderKanban }],
    },
  ]

  if (project) {
    const items: NavGroup['items'] = []
    if (project.is_epics_activated)
      items.push({
        title: 'Epics',
        url: `/p/${project.slug}/epics`,
        icon: Layers,
      })
    if (project.is_backlog_activated)
      items.push({
        title: 'Backlog',
        url: `/p/${project.slug}/backlog`,
        icon: ListOrdered,
      })
    if (project.is_backlog_activated)
      items.push({
        title: 'Taskboard',
        url: `/p/${project.slug}/taskboard`,
        icon: LayoutGrid,
      })
    if (project.is_kanban_activated)
      items.push({
        title: 'Kanban',
        url: `/p/${project.slug}/kanban`,
        icon: Columns3,
      })
    if (project.is_issues_activated)
      items.push({
        title: 'Issues',
        url: `/p/${project.slug}/issues`,
        icon: Bug,
      })
    if (items.length) groups.push({ title: project.name, items })
  }

  groups.push({
    title: 'You',
    items: [
      { title: 'Appearance', url: '/settings/appearance', icon: Palette },
    ],
  })
  return groups
}
