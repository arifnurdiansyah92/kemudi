import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import {
  Compass,
  UserCog,
  Settings,
  House,
  BookOpen,
  Users,
  Bug,
  Layers,
  Columns3,
  FolderKanban,
  LayoutGrid,
  ListOrdered,
  Palette,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { projectQuery } from '@/lib/taiga/queries'
import { type NavGroup } from './types'

/** Sidebar groups: the workspace, then the open project's views. */
export function useNavGroups(): NavGroup[] {
  const { t } = useTranslation(['shell', 'common'])
  const { slug } = useParams({ strict: false }) as { slug?: string }
  const { data: project } = useQuery({
    ...projectQuery(slug ?? ''),
    enabled: !!slug,
  })

  const groups: NavGroup[] = [
    {
      title: t('nav.workspace'),
      items: [
        { title: t('nav.home'), url: '/', icon: House },
        {
          title: t('common:terms.project_other'),
          url: '/projects',
          icon: FolderKanban,
        },
        { title: t('nav.discover'), url: '/discover', icon: Compass },
      ],
    },
  ]

  if (project) {
    const items: NavGroup['items'] = []
    if (project.is_epics_activated)
      items.push({
        title: t('common:terms.epic_other'),
        url: `/p/${project.slug}/epics`,
        icon: Layers,
      })
    if (project.is_backlog_activated)
      items.push({
        title: t('common:terms.backlog'),
        url: `/p/${project.slug}/backlog`,
        icon: ListOrdered,
      })
    if (project.is_backlog_activated)
      items.push({
        title: t('common:terms.taskboard'),
        url: `/p/${project.slug}/taskboard`,
        icon: LayoutGrid,
      })
    if (project.is_kanban_activated)
      items.push({
        title: t('common:terms.kanban'),
        url: `/p/${project.slug}/kanban`,
        icon: Columns3,
      })
    if (project.is_issues_activated)
      items.push({
        title: t('common:terms.issue_other'),
        url: `/p/${project.slug}/issues`,
        icon: Bug,
      })
    if (project.is_wiki_activated)
      items.push({
        title: t('common:terms.wiki'),
        url: `/p/${project.slug}/wiki`,
        icon: BookOpen,
      })
    items.push({
      title: t('common:terms.team'),
      url: `/p/${project.slug}/team`,
      icon: Users,
    })
    if (project.i_am_admin)
      items.push({
        title: t('common:terms.settings'),
        url: `/p/${project.slug}/settings`,
        icon: Settings,
      })
    if (items.length) groups.push({ title: project.name, items })
  }

  groups.push({
    title: t('nav.you'),
    items: [
      {
        title: t('userMenu.settings'),
        url: '/settings/profile',
        icon: UserCog,
      },
      {
        title: t('userMenu.appearance'),
        url: '/settings/appearance',
        icon: Palette,
      },
    ],
  })
  return groups
}
