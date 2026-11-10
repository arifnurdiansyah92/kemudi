import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { ForgotPasswordForm } from './forgot-password-form'

const mocks = vi.hoisted(() => ({ requestPasswordReset: vi.fn() }))

vi.mock('@/lib/taiga/client', async (orig) => ({
  ...(await orig<typeof import('@/lib/taiga/client')>()),
  requestPasswordReset: mocks.requestPasswordReset,
}))

describe('ForgotPasswordForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('asks for a username before sending', async () => {
    const screen = await render(<ForgotPasswordForm />)
    await userEvent.click(
      screen.getByRole('button', { name: /^Send reset link$/i })
    )

    await expect
      .element(screen.getByText('Enter your username or email.'))
      .toBeInTheDocument()
    expect(mocks.requestPasswordReset).not.toHaveBeenCalled()
  })

  it('requests the reset and confirms without revealing whether the account exists', async () => {
    mocks.requestPasswordReset.mockResolvedValue(undefined)
    const screen = await render(<ForgotPasswordForm />)
    await userEvent.fill(
      screen.getByLabelText(/^Username or email$/i),
      'webdev'
    )
    await userEvent.click(
      screen.getByRole('button', { name: /^Send reset link$/i })
    )

    await vi.waitFor(() =>
      expect(mocks.requestPasswordReset).toHaveBeenCalledWith('webdev')
    )
    await expect
      .element(screen.getByText(/If an account matches/))
      .toBeInTheDocument()
  })

  it('shows an error when the request fails', async () => {
    mocks.requestPasswordReset.mockRejectedValue(new Error('offline'))
    const screen = await render(<ForgotPasswordForm />)
    await userEvent.fill(
      screen.getByLabelText(/^Username or email$/i),
      'webdev'
    )
    await userEvent.click(
      screen.getByRole('button', { name: /^Send reset link$/i })
    )

    await expect
      .element(screen.getByText('The reset email was not sent. Try again.'))
      .toBeInTheDocument()
  })
})
