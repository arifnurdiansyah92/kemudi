import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { SignOutDialog } from './sign-out-dialog'

const mocks = vi.hoisted(() => ({ navigate: vi.fn(), reset: vi.fn() }))

vi.mock('@/stores/auth-store', () => ({
  useAuthStore: (select: (s: { reset: () => void }) => unknown) =>
    select({ reset: mocks.reset }),
}))

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return { ...actual, useNavigate: () => mocks.navigate }
})

function renderDialog(queryClient = new QueryClient()) {
  return render(
    <QueryClientProvider client={queryClient}>
      <SignOutDialog open onOpenChange={vi.fn()} />
    </QueryClientProvider>
  )
}

describe('SignOutDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('clears the session and cached data, then goes to sign-in', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['projects', 6], [{ id: 1 }])
    const { getByRole } = await renderDialog(queryClient)

    await userEvent.click(getByRole('button', { name: /^Sign out$/i }))

    expect(mocks.reset).toHaveBeenCalledOnce()
    expect(queryClient.getQueryData(['projects', 6])).toBeUndefined()
    expect(mocks.navigate).toHaveBeenCalledWith({
      to: '/sign-in',
      replace: true,
    })
  })

  it('does nothing when Cancel is clicked', async () => {
    const { getByRole } = await renderDialog()

    await userEvent.click(getByRole('button', { name: /^Cancel$/i }))

    expect(mocks.reset).not.toHaveBeenCalled()
    expect(mocks.navigate).not.toHaveBeenCalled()
  })
})
