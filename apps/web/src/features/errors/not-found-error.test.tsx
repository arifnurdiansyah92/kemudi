import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { NotFoundError } from './not-found-error'

function renderAt(path: string) {
  const rootRoute = createRootRoute()
  const router = createRouter({
    routeTree: rootRoute.addChildren([
      createRoute({
        getParentRoute: () => rootRoute,
        path: '/',
        component: () => <div>home page</div>,
      }),
      createRoute({
        getParentRoute: () => rootRoute,
        path: '/projects',
        component: () => <div>projects list</div>,
      }),
    ]),
    history: createMemoryHistory({ initialEntries: [path] }),
    defaultNotFoundComponent: NotFoundError,
  })
  return render(<RouterProvider router={router} />)
}

describe('NotFoundError', () => {
  it('offers a Back to projects button that opens /projects', async () => {
    const screen = await renderAt('/no-such-page')

    await userEvent.click(
      screen.getByRole('link', { name: 'Back to projects' })
    )

    await expect
      .element(screen.getByText('projects list'))
      .toBeInTheDocument()
  })
})
