import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { ProjectSummary } from '@/lib/taiga/types'
import { ProjectList } from './project-list'

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    Link: ({
      children,
      to,
      params,
    }: {
      children?: React.ReactNode
      to: string
      params?: { slug?: string }
    }) => <a href={params?.slug ?? to}>{children}</a>,
  }
})

function project(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: 1,
    name: 'Project',
    slug: 'project',
    description: '',
    logo_small_url: null,
    is_private: false,
    is_backlog_activated: true,
    is_kanban_activated: false,
    is_issues_activated: true,
    i_am_admin: true,
    i_am_member: true,
    total_milestones: null,
    total_story_points: null,
    modified_date: '2026-11-13T10:00:00Z',
    my_permissions: [],
    members: [],
    ...overrides,
  }
}

async function renderList(projects: ProjectSummary[]) {
  const client = new QueryClient()
  return await render(
    <QueryClientProvider client={client}>
      <ProjectList projects={projects} />
    </QueryClientProvider>
  )
}

describe('ProjectList', () => {
  it('marks private projects with a Private label', async () => {
    const screen = await renderList([
      project({ id: 1, name: 'Secret', slug: 'secret', is_private: true }),
      project({ id: 2, name: 'Open', slug: 'open', is_private: false }),
    ])

    await expect.element(screen.getByText('Private')).toBeInTheDocument()
    expect(screen.getByText('Private').elements()).toHaveLength(1)

    const secret = screen.getByText('Secret').element().closest('a')
    const open = screen.getByText('Open').element().closest('a')
    expect(secret?.textContent).toContain('Private')
    expect(open?.textContent).not.toContain('Private')
  })
})
