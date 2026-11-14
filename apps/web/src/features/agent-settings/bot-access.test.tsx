import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { AgentSettings } from '@/lib/kemudi-ai/agent'
import { BotAccessNotice, LastError } from './bot-access'

const give = vi.hoisted(() => ({ mutate: vi.fn() }))

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useGiveBotAccess: () => ({ mutate: give.mutate, isPending: false }),
}))

const settings: AgentSettings = {
  enabled: true,
  merge_mode: 'approve',
  deploy_command: '',
  deploy_command_set: false,
  executor: 'local',
  ssh_host: '',
  ssh_port: 22,
  ssh_user: '',
  ssh_public_key: null,
  ssh_fingerprint: null,
  preflight: {},
  remote_execution: false,
  bot_access: { ok: false, member: false, error: 'not a member' },
  last_error: null,
  last_error_at: null,
  updated_by: null,
  updated_at: null,
}

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
  )
}

describe('BotAccessNotice', () => {
  it('lets an admin give Awak access', async () => {
    const screen = await render(
      wrap(<BotAccessNotice slug='playfast' settings={settings} canEdit />)
    )
    await expect
      .element(screen.getByText("Awak can't open this project"))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Give Awak access' }).click()
    expect(give.mutate).toHaveBeenCalledOnce()
  })

  it('asks a member to find an admin', async () => {
    const screen = await render(
      wrap(
        <BotAccessNotice slug='playfast' settings={settings} canEdit={false} />
      )
    )
    await expect
      .element(screen.getByText('Ask a project admin to give Awak access.'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Give Awak access' }))
      .not.toBeInTheDocument()
  })

  it('stays hidden when the bot has access or Awak is off', async () => {
    const ok = await render(
      wrap(
        <BotAccessNotice
          slug='playfast'
          settings={{
            ...settings,
            bot_access: { ok: true, member: true, error: null },
          }}
          canEdit
        />
      )
    )
    await expect.element(ok.getByRole('alert')).not.toBeInTheDocument()
    const off = await render(
      wrap(
        <BotAccessNotice
          slug='playfast'
          settings={{ ...settings, enabled: false }}
          canEdit
        />
      )
    )
    await expect.element(off.getByRole('alert')).not.toBeInTheDocument()
  })
})

describe('LastError', () => {
  it('shows the worker problem quietly', async () => {
    const screen = await render(
      <LastError
        settings={{ ...settings, last_error: 'Taiga refused the request' }}
      />
    )
    await expect
      .element(screen.getByText('Taiga refused the request'))
      .toBeVisible()
  })
})
