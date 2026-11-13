import { type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { SidebarProvider } from '@/components/ui/sidebar'
import { NavGroup } from './nav-group'

vi.mock('@tanstack/react-router', () => ({
  Link: ({ to, children }: { to: string; children: ReactNode }) => (
    <a href={to}>{children}</a>
  ),
  useLocation: ({ select }: { select: (l: { href: string }) => string }) =>
    select({ href: '/' }),
}))

describe('NavGroup', () => {
  it('shows the count badge on the Projects item', async () => {
    const screen = await render(
      <SidebarProvider>
        <NavGroup
          title='Workspace'
          items={[{ title: 'Projects', url: '/projects', badge: '3' }]}
        />
      </SidebarProvider>
    )

    await expect.element(screen.getByText('3')).toBeInTheDocument()
    await expect
      .element(screen.getByText('Projects').element().closest('a')!)
      .toHaveTextContent('Projects3')
  })
})
