import { AxiosError, type AxiosResponse } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { RunbookState, SetupRun } from '@/lib/kemudi-ai/agent'
import { RunbookCard } from './runbook'

const state = vi.hoisted(() => ({
  runbook: null as RunbookState | null,
  run: null as SetupRun | null,
  mutate: vi.fn(),
  start: vi.fn(),
}))

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useRunbook: () => ({
    isPending: false,
    isError: false,
    data: state.runbook,
  }),
  useSaveRunbook: () => ({ mutate: state.mutate, isPending: false }),
  useSetupLatest: () => ({ isPending: false, data: state.run }),
  useStartSetup: () => ({ mutate: state.start, isPending: false }),
  useCancelSetup: () => ({ mutate: vi.fn(), isPending: false }),
}))

const empty: RunbookState = {
  runbook: null,
  version: 0,
  approved_by: '',
  approved_at: null,
}

const playfast: RunbookState = {
  runbook: {
    apps: [
      {
        name: 'web',
        repo: 'pf-web',
        dir: 'frontend',
        install: ['pnpm install --frozen-lockfile'],
        checks: ['pnpm exec tsc --noEmit', 'pnpm lint'],
        build: [],
        env: { INTERNAL_API_URL: '{services.api.url}' },
        generated: ['public/icons/*.svg'],
      },
    ],
    services: [
      {
        name: 'web',
        kind: 'process',
        app: 'web',
        command: 'pnpm exec next dev --port {port}',
        health: '/',
        ready_timeout: 240,
      },
    ],
    env: [
      {
        name: 'JWT_SECRET_KEY',
        secret: true,
        required: true,
        description: 'any 64-char hex for testing',
      },
    ],
    seed: null,
    qa: { service: 'web', env: ['QA_ADMIN_EMAIL'] },
    future_field: { kept: true },
  },
  version: 3,
  approved_by: 'arif',
  approved_at: '2026-11-14T03:00:00Z',
}

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
  )
}

function unprocessable(detail: unknown) {
  return new AxiosError('Unprocessable', 'ERR_BAD_REQUEST', undefined, null, {
    status: 422,
    data: { detail },
  } as AxiosResponse)
}

beforeEach(() => {
  state.mutate.mockReset()
  state.start.mockReset()
  state.run = null
})

describe('RunbookCard', () => {
  it('explains the empty state and lets an admin paste one', async () => {
    state.runbook = empty
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await expect.element(screen.getByText('No runbook yet')).toBeVisible()
    await expect
      .element(screen.getByText(/Configure automatically lets Awak/))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Paste runbook JSON' }).click()
    await expect
      .element(screen.getByRole('textbox', { name: 'Runbook JSON' }))
      .toHaveValue(JSON.stringify({ apps: [], services: [], env: [] }, null, 2))
  })

  it('gives members no edit button', async () => {
    state.runbook = empty
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit={false} />))
    await expect
      .element(screen.getByText(/A project admin can configure it/))
      .toBeVisible()
    expect(screen.getByRole('button').elements()).toHaveLength(0)
  })

  it('starts Configure automatically', async () => {
    state.runbook = empty
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await screen
      .getByRole('button', { name: 'Configure automatically' })
      .click()
    expect(state.start).toHaveBeenCalledOnce()
  })

  it('holds Configure automatically back while a run is going', async () => {
    state.runbook = playfast
    state.run = {
      id: 7,
      project_slug: 'pf',
      state: 'proving',
      active: true,
      round: 1,
      max_rounds: 3,
      proposal: {
        runbook: null,
        draft: {},
        env_help: {},
        report: '',
        feedback: '',
      },
      steps: [],
      missing_env: [],
      screenshot: false,
      resources: {},
      error: '',
      cost_idr: 0,
      created_by: 'arif',
      created_at: '2026-11-14T03:00:00Z',
      updated_at: '2026-11-14T03:01:00Z',
    }
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await expect
      .element(screen.getByRole('button', { name: 'Configure automatically' }))
      .toBeDisabled()
    await expect
      .element(screen.getByText('A setup run is in progress.'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('region', { name: 'Setup Assistant' }))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Edit JSON' }))
      .toBeEnabled()
  })

  it('summarises apps, services, env and who approved it', async () => {
    state.runbook = playfast
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await expect
      .element(screen.getByText(/Version 3 · approved by arif/))
      .toBeVisible()
    await expect.element(screen.getByText('pf-web / frontend')).toBeVisible()
    await expect.element(screen.getByText('pnpm lint')).toBeVisible()
    await expect
      .element(screen.getByText('pnpm exec next dev --port {port}'))
      .toBeVisible()
    await expect.element(screen.getByText('/ within 240 s')).toBeVisible()
    await expect.element(screen.getByText('QA opens this')).toBeVisible()
    await expect.element(screen.getByText('JWT_SECRET_KEY')).toBeVisible()
    await expect.element(screen.getByText('QA_ADMIN_EMAIL')).toBeVisible()
    await expect.element(screen.getByText('Generated')).toBeVisible()
    await expect.element(screen.getByText('public/icons/*.svg')).toBeVisible()
  })

  it('shows the server defaults for a service without health or timeout', async () => {
    state.runbook = {
      ...playfast,
      runbook: {
        ...playfast.runbook!,
        services: [
          {
            name: 'web',
            kind: 'process',
            app: 'web',
            command: 'pnpm exec next dev --port {port}',
          },
        ],
      },
    }
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await expect.element(screen.getByText('/ within 120 s')).toBeVisible()
  })

  it('shows compose services with init, seed, run_in and the QA login', async () => {
    state.runbook = {
      ...playfast,
      runbook: {
        ...playfast.runbook!,
        apps: [
          ...playfast.runbook!.apps!,
          {
            name: 'api',
            repo: 'pf-web',
            dir: 'backend',
            run_in: 'api:backend',
            checks: ['python -m pytest -q tests'],
          },
        ],
        services: [
          {
            name: 'api',
            kind: 'compose',
            repo: 'pf-web',
            file: 'docker-compose.yml',
            compose_services: ['postgres', 'redis', 'backend'],
            expose: 'backend:5000',
            health: '/api/health',
            env: ['JWT_SECRET_KEY'],
          },
          ...playfast.runbook!.services!,
        ],
        init: [
          { service: 'api:backend', command: 'python scripts/init_qa.py' },
        ],
        seed: { service: 'api', command: 'python scripts/seed_campaigns.py' },
        qa: {
          service: 'web',
          env: ['QA_ADMIN_EMAIL'],
          login: {
            path: '/login',
            fields: { 'input[type=email]': '{env.QA_ADMIN_EMAIL}' },
            submit: 'button[type=submit]',
            success_url: '/store',
          },
        },
      },
    }
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await expect
      .element(
        screen.getByText(
          'pf-web / docker-compose.yml · postgres, redis, backend'
        )
      )
      .toBeVisible()
    await expect.element(screen.getByText('backend:5000')).toBeVisible()
    await expect
      .element(screen.getByText('backend: python scripts/init_qa.py'))
      .toBeVisible()
    await expect
      .element(screen.getByText('python scripts/seed_campaigns.py'))
      .toBeVisible()
    await expect.element(screen.getByText('runs in api:backend')).toBeVisible()
    await expect.element(screen.getByText('QA login')).toBeVisible()
    await expect.element(screen.getByText('/login → /store')).toBeVisible()
  })

  it('keeps unknown fields when editing', async () => {
    state.runbook = playfast
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Edit JSON' }).click()
    await screen.getByRole('button', { name: 'Save and approve' }).click()
    expect(state.mutate).toHaveBeenCalledOnce()
    expect(state.mutate.mock.calls[0][0]).toEqual(playfast.runbook)
  })

  it('stops on JSON that does not parse', async () => {
    state.runbook = empty
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Paste runbook JSON' }).click()
    await screen
      .getByRole('textbox', { name: 'Runbook JSON' })
      .fill('{"apps": [')
    await screen.getByRole('button', { name: 'Save and approve' }).click()
    await expect
      .element(screen.getByRole('alert'))
      .toHaveTextContent(/This isn't valid JSON/)
    expect(state.mutate).not.toHaveBeenCalled()
  })

  it('lists every problem the server finds', async () => {
    state.runbook = empty
    state.mutate.mockImplementation(
      (_body: unknown, opts: { onError: (e: unknown) => void }) =>
        opts.onError(
          unprocessable([
            'apps.0.repo: no repo named pf-api in this project',
            'services.0.command: rm is not an allowed program',
          ])
        )
    )
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Paste runbook JSON' }).click()
    await screen.getByRole('button', { name: 'Save and approve' }).click()
    const alert = screen.getByRole('alert')
    await expect.element(alert).toHaveTextContent('Not saved: 2 problems')
    await expect.element(alert.getByText(/no repo named pf-api/)).toBeVisible()
    await expect
      .element(alert.getByText(/rm is not an allowed program/))
      .toBeVisible()
  })

  it('shows a single server message too', async () => {
    state.runbook = empty
    state.mutate.mockImplementation(
      (_body: unknown, opts: { onError: (e: unknown) => void }) =>
        opts.onError(unprocessable('qa.service must name a service'))
    )
    const screen = await render(wrap(<RunbookCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Paste runbook JSON' }).click()
    await screen.getByRole('button', { name: 'Save and approve' }).click()
    await expect
      .element(screen.getByRole('alert'))
      .toHaveTextContent(/Not saved: 1 problem.*qa.service must name a service/)
  })
})
