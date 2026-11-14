import { type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from 'vitest-browser-react'
import { useAuthStore } from '@/stores/auth-store'
import { useNavGroups } from './use-nav-groups'

vi.mock('@tanstack/react-router', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@tanstack/react-router')>()),
  useParams: () => ({}),
}))

/** The project count the sidebar badge should show, seeded as the cache would. */
function projectsCache(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    name: `Project ${i + 1}`,
    slug: `project-${i + 1}`,
  }))
}

async function renderNavGroups(projectCount: number, kemudiAdmin = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  client.setQueryData(['projects', 1], projectsCache(projectCount))
  client.setQueryData(['kemudi-ai', 'me'], {
    id: 1,
    username: 'awak',
    kemudi_admin: kemudiAdmin,
  })
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return await renderHook(() => useNavGroups(), { wrapper: Wrapper })
}

function projectsItem(groups: ReturnType<typeof useNavGroups>) {
  const item = groups
    .flatMap((group) => group.items)
    .find((navItem) => navItem.url === '/projects')
  expect(item).toBeDefined()
  return item!
}

describe('useNavGroups', () => {
  beforeEach(() => {
    useAuthStore.setState({
      session: {
        token: 'token',
        refresh: 'refresh',
        user: { id: 1, username: 'awak' },
      } as never,
    })
  })

  it('badges the Projects item with how many projects the user follows', async () => {
    const { result } = await renderNavGroups(3)

    expect(projectsItem(result.current).badge).toBe('3')
  })

  it('shows no badge when the user follows no project', async () => {
    const { result } = await renderNavGroups(0)

    expect(projectsItem(result.current).badge).toBeUndefined()
  })

  it('shows Skills only to Kemudi admins', async () => {
    const urls = (groups: ReturnType<typeof useNavGroups>) =>
      groups.flatMap((group) => group.items).map((item) => item.url)

    const member = await renderNavGroups(1, false)
    expect(urls(member.result.current)).not.toContain('/skills')

    const admin = await renderNavGroups(1, true)
    expect(urls(admin.result.current)).toContain('/skills')
  })
})
