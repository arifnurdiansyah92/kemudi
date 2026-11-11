import { AxiosError, AxiosHeaders } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { UserAuthForm } from './user-auth-form'

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  signIn: vi.fn(),
}))

vi.mock('@/lib/taiga/client', async (orig) => ({
  ...(await orig<typeof import('@/lib/taiga/client')>()),
  signIn: mocks.signIn,
}))

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  return {
    ...actual,
    useNavigate: () => mocks.navigate,
    Link: ({ children, to }: { children?: React.ReactNode; to: string }) => (
      <a href={to}>{children}</a>
    ),
  }
})

function taigaError(status: number, data: unknown) {
  return new AxiosError('Request failed', String(status), undefined, null, {
    status,
    statusText: '',
    data,
    headers: {},
    config: { headers: new AxiosHeaders() },
  })
}

async function fillAndSubmit(
  screen: Awaited<ReturnType<typeof render>>,
  username = 'webdev',
  password = 'secret'
) {
  await userEvent.fill(screen.getByLabelText(/^Username or email$/i), username)
  await userEvent.fill(screen.getByLabelText(/^Password$/i), password)
  await userEvent.click(screen.getByRole('button', { name: /^Sign in$/i }))
}

describe('UserAuthForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('asks for both fields before calling the API', async () => {
    const screen = await render(<UserAuthForm />)
    await userEvent.click(screen.getByRole('button', { name: /^Sign in$/i }))

    await expect
      .element(screen.getByText('Enter your username or email.'))
      .toBeInTheDocument()
    await expect
      .element(screen.getByText('Enter your password.'))
      .toBeInTheDocument()
    expect(mocks.signIn).not.toHaveBeenCalled()
  })

  it('signs in and goes to the projects list by default', async () => {
    mocks.signIn.mockResolvedValue({ id: 6 })
    const screen = await render(<UserAuthForm />)
    await fillAndSubmit(screen)

    await vi.waitFor(() =>
      expect(mocks.signIn).toHaveBeenCalledWith('webdev', 'secret')
    )
    await vi.waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith({ to: '/', replace: true })
    )
  })

  it('returns to a same-origin redirect after signing in', async () => {
    mocks.signIn.mockResolvedValue({ id: 6 })
    const screen = await render(
      <UserAuthForm redirectTo='/p/kemudi-demo/kanban?story=3' />
    )
    await fillAndSubmit(screen)

    await vi.waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith({
        to: '/p/kemudi-demo/kanban?story=3',
        replace: true,
      })
    )
  })

  it('ignores a redirect to another origin', async () => {
    mocks.signIn.mockResolvedValue({ id: 6 })
    const screen = await render(
      <UserAuthForm redirectTo='https://evil.example/phish' />
    )
    await fillAndSubmit(screen)

    await vi.waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith({ to: '/', replace: true })
    )
  })

  it("shows the server's message when the credentials are wrong", async () => {
    mocks.signIn.mockRejectedValue(
      taigaError(400, {
        _error_message: 'Username or password does not match user.',
      })
    )
    const screen = await render(<UserAuthForm />)
    await fillAndSubmit(screen)

    await expect
      .element(screen.getByText('Username or password does not match user.'))
      .toBeInTheDocument()
    expect(mocks.navigate).not.toHaveBeenCalled()
  })
})
