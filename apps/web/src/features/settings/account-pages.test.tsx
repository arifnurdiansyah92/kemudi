import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { ProfileSettings } from './account-pages'

const { me } = vi.hoisted(() => ({
  me: {
    id: 7,
    username: 'budi',
    full_name: 'Budi Santoso',
    full_name_display: 'Budi Santoso',
    email: 'budi@example.com',
    photo: null,
    big_photo: null,
    color: '#123456',
    gravatar_id: '',
    lang: 'en',
    timezone: 'Asia/Jakarta',
    is_active: true,
    bio: '',
    theme: 'light',
    verified_email: true,
    date_joined: '2026-01-01T00:00:00Z',
  },
}))

vi.mock('@/lib/taiga/account', () => ({
  useMe: () => ({ data: me }),
  useAvatar: () => ({
    change: { mutate: vi.fn(), isPending: false },
    remove: { mutate: vi.fn(), isPending: false },
  }),
  useUpdateMe: () => ({ mutate: vi.fn(), isPending: false }),
  useLocales: () => ({ data: [] }),
  useApplicationTokens: () => ({
    list: { isPending: false, data: [] },
    revoke: { mutate: vi.fn() },
  }),
  useNotifyPolicies: () => ({ isPending: false, data: [] }),
  useUpdateNotifyPolicy: () => ({ mutate: vi.fn() }),
  useDeleteAccount: () => ({ mutate: vi.fn(), isPending: false }),
  useChangePassword: () => ({ mutate: vi.fn(), isPending: false }),
}))

describe('ProfileSettings', () => {
  it('shows the username with @ directly below the full name', async () => {
    const screen = await render(<ProfileSettings />)

    await expect.element(screen.getByText('Budi Santoso')).toBeInTheDocument()
    const username = screen.getByText('@budi').element()

    expect(username.previousElementSibling?.textContent).toBe('Budi Santoso')
  })
})
