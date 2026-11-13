import { type ReactNode } from 'react'
import { AxiosError, AxiosHeaders } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { IntakeDraftOut } from '@/lib/kemudi-ai/agent'
import { api } from '@/lib/taiga/client'
import { Intake } from './index'

const mocks = vi.hoisted(() => ({ admin: true }))

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    search,
    className,
  }: {
    children: ReactNode
    search?: { ref?: number }
    className?: string
  }) => (
    <a href={search?.ref ? `?ref=${search.ref}` : '#'} className={className}>
      {children}
    </a>
  ),
}))

vi.mock('@/components/layout/app-header', () => ({ AppHeader: () => null }))

vi.mock('@/features/project/use-project', () => ({
  useProject: () => ({
    id: 1,
    slug: 'demo',
    name: 'Demo',
    i_am_admin: mocks.admin,
  }),
}))

const drafts: IntakeDraftOut[] = [
  {
    subject: 'Login with email',
    description: 'Users sign in.',
    criteria: ['Wrong password shows an error'],
    area: 'web',
    ready: true,
    reason: '',
  },
  {
    subject: 'Export invoices',
    description: '',
    criteria: [],
    area: 'backend',
    ready: false,
    reason: 'no criteria',
  },
  {
    subject: 'Audit log',
    description: '',
    criteria: ['Every change is logged'],
    area: 'both',
    ready: true,
    reason: '',
  },
]

function settings(enabled: boolean) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url.endsWith('/agent/settings')) return { data: { enabled } }
    throw new Error(`unexpected GET ${url}`)
  })
}

async function renderIntake() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return await render(
    <QueryClientProvider client={client}>
      <Intake />
    </QueryClientProvider>
  )
}

function axiosError(status: number, detail: string) {
  return new AxiosError('fail', String(status), undefined, undefined, {
    status,
    statusText: '',
    data: { detail },
    headers: {},
    config: { headers: new AxiosHeaders() },
  })
}

describe('Intake', () => {
  beforeEach(() => {
    mocks.admin = true
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('drafts, edits and creates stories, sending hold and leaving out removed drafts', async () => {
    settings(true)
    const post = vi
      .spyOn(api, 'post')
      .mockImplementation(async (url: string) => {
        if (url.endsWith('/intake/draft')) return { data: { drafts } }
        if (url.endsWith('/intake/create'))
          return {
            data: {
              stories: [
                {
                  id: 41,
                  ref: 12,
                  subject: 'Login by email',
                  ready: false,
                  reason: 'edited',
                },
                {
                  id: 42,
                  ref: 13,
                  subject: 'Audit log',
                  ready: false,
                  reason: 'held',
                },
              ],
            },
          }
        throw new Error(`unexpected POST ${url}`)
      })

    const screen = await renderIntake()
    await screen.getByLabelText('Text').fill('Client wants login and exports')
    await screen.getByRole('button', { name: 'Draft stories' }).click()

    const [draftUrl, form, config] = post.mock.calls[0] as [
      string,
      FormData,
      { headers?: Record<string, string> },
    ]
    expect(draftUrl).toBe('/projects/demo/intake/draft')
    expect(form.get('text')).toBe('Client wants login and exports')
    expect(form.get('lang')).toBe('en')
    // The shared client defaults to JSON; without this axios sends JSON.
    expect(config.headers?.['Content-Type']).toBe('multipart/form-data')

    await expect
      .element(screen.getByText('Goes to Ready').first())
      .toBeVisible()
    await expect.element(screen.getByText('Waits in New')).toBeVisible()
    await expect.element(screen.getByText('· no criteria')).toBeVisible()

    // Edit story 1: its Ready pill becomes a recheck.
    const subject = screen.getByLabelText('Subject').first()
    await subject.fill('Login by email')
    await expect.element(screen.getByText('Rechecked on create')).toBeVisible()
    await screen.getByRole('button', { name: 'Add criterion' }).first().click()
    await screen
      .getByRole('textbox', { name: 'Criterion 2' })
      .fill('Locked after 5 tries')

    // Drop story 2, hold story 3 (now story 2).
    await screen.getByRole('button', { name: 'Remove story 2' }).click()
    await screen.getByLabelText('Hold back in New').nth(1).click()
    await expect.element(screen.getByText('Held in New')).toBeVisible()

    await screen.getByRole('button', { name: 'Create 2 stories' }).click()

    const [createUrl, body] = post.mock.calls[1] as [
      string,
      { drafts: unknown },
    ]
    expect(createUrl).toBe('/projects/demo/intake/create')
    expect(body.drafts).toEqual([
      {
        subject: 'Login by email',
        description: 'Users sign in.',
        criteria: ['Wrong password shows an error', 'Locked after 5 tries'],
        area: 'web',
        hold: false,
      },
      {
        subject: 'Audit log',
        description: '',
        criteria: ['Every change is logged'],
        area: 'both',
        hold: true,
      },
    ])

    await expect.element(screen.getByText('Created 2 stories')).toBeVisible()
    await expect
      .element(screen.getByRole('link', { name: '#12' }))
      .toHaveAttribute('href', '?ref=12')
  })

  it('keeps the drafts and edits when create fails', async () => {
    settings(true)
    vi.spyOn(api, 'post').mockImplementation(async (url: string) => {
      if (url.endsWith('/intake/draft')) return { data: { drafts } }
      throw axiosError(
        403,
        'Taiga does not let you add stories to this project'
      )
    })

    const screen = await renderIntake()
    await screen.getByLabelText('Text').fill('brief')
    await screen.getByRole('button', { name: 'Draft stories' }).click()
    await screen.getByLabelText('Subject').first().fill('Login, edited')
    await screen.getByRole('button', { name: 'Create 3 stories' }).click()

    await expect
      .element(
        screen.getByText('Taiga does not let you add stories to this project')
      )
      .toBeVisible()
    await expect
      .element(screen.getByLabelText('Subject').first())
      .toHaveValue('Login, edited')
    await expect
      .element(screen.getByRole('button', { name: 'Create 3 stories' }))
      .toBeEnabled()
  })

  it('says stories wait when Awak is off, linking admins to the setting', async () => {
    settings(false)
    const screen = await renderIntake()
    await expect
      .element(screen.getByText('Awak is off for this project'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('link', { name: /Settings → Agent/ }))
      .toBeVisible()
  })
})
