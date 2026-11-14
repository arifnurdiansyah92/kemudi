import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { SetupRun } from '@/lib/kemudi-ai/agent'
import { SetupAssistant } from './setup-assistant'

const state = vi.hoisted(() => ({
  env: vi.fn(),
  approve: vi.fn(),
  cancel: vi.fn(),
}))

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useSetupEnv: () => ({ mutate: state.env, isPending: false }),
  useApproveSetup: () => ({ mutate: state.approve, isPending: false }),
  useCancelSetup: () => ({ mutate: state.cancel, isPending: false }),
  useSetupScreenshot: () => ({
    isPending: false,
    isError: false,
    data: new Blob([new Uint8Array([137, 80, 78, 71])], { type: 'image/png' }),
  }),
}))

const base: SetupRun = {
  id: 7,
  project_slug: 'pf',
  state: 'queued',
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
  confirm_env: [],
  confirmed_env: [],
  screenshot: false,
  resources: {},
  error: '',
  cost_idr: 0,
  created_by: 'arif',
  created_at: '2026-11-14T03:00:00Z',
  updated_at: '2026-11-14T03:05:00Z',
}

const proposed: SetupRun['proposal'] = {
  runbook: {
    apps: [
      { name: 'web', repo: 'pf-web', dir: 'frontend', checks: ['pnpm lint'] },
    ],
    services: [
      {
        name: 'web',
        kind: 'process',
        app: 'web',
        command: 'pnpm exec next dev --port {port}',
      },
    ],
    env: [],
    qa: { service: 'web' },
  },
  draft: { 'pf-web': {} },
  env_help: {},
  report: 'Next.js app in frontend/.',
  feedback: '',
}

const steps: SetupRun['steps'] = [
  { name: 'install web', ok: true, output: 'added 812 packages' },
  {
    name: 'checks web',
    ok: false,
    red: true,
    output: 'ok  tsc\nRED pnpm lint',
    gates: [
      { name: 'tsc', ok: true },
      { name: 'pnpm lint', ok: false },
    ],
  },
  { name: 'service web', ok: true, output: '' },
]

function show(run: Partial<SetupRun>, opts: { canEdit?: boolean } = {}) {
  const onRetry = vi.fn()
  return {
    onRetry,
    screen: render(
      <QueryClientProvider client={new QueryClient()}>
        <SetupAssistant
          slug='pf'
          run={{ ...base, ...run }}
          canEdit={opts.canEdit ?? true}
          qaMode='gates'
          onRetry={onRetry}
          retrying={false}
        />
      </QueryClientProvider>
    ),
  }
}

beforeEach(() => {
  state.env.mockReset()
  state.approve.mockReset()
  state.cancel.mockReset()
})

describe('SetupAssistant', () => {
  it('shows proving with the fix round, the timeline and step logs', async () => {
    const { screen: s } = show({
      state: 'proving',
      round: 2,
      proposal: proposed,
      steps,
      cost_idr: 1250,
    })
    const screen = await s
    await expect.element(screen.getByText('Round 2 of 3')).toBeVisible()
    await expect
      .element(screen.getByRole('listitem').filter({ hasText: 'Proving' }))
      .toHaveAttribute('aria-current', 'step')
    await expect.element(screen.getByText('install web')).toBeVisible()
    await expect.element(screen.getByText('1 of 2 checks passed')).toBeVisible()
    await expect.element(screen.getByText('Cost Rp1,250')).toBeVisible()
    await expect.element(screen.getByText(/RED pnpm lint/)).not.toBeVisible()
    await screen.getByText('checks web').click()
    await expect.element(screen.getByText(/RED pnpm lint/)).toBeVisible()
    await screen.getByRole('button', { name: 'Cancel run' }).click()
    expect(state.cancel).toHaveBeenCalledWith(7)
  })

  it('asks for missing env values and sends only the filled ones', async () => {
    const { screen: s } = show({
      state: 'needs_input',
      proposal: proposed,
      missing_env: [
        {
          name: 'JWT_SECRET_KEY',
          description: 'any 64-char hex',
          secret: true,
        },
        { name: 'QA_ADMIN_EMAIL', description: '', secret: false },
        { name: 'SMTP_PASSWORD', description: '', secret: true },
      ],
    })
    const screen = await s
    await expect
      .element(
        screen.getByRole('listitem').filter({ hasText: 'Waiting for env' })
      )
      .toHaveAttribute('aria-current', 'step')
    await screen.getByRole('button', { name: 'Save and continue' }).click()
    await expect
      .element(screen.getByRole('alert'))
      .toHaveTextContent('Enter at least one value.')
    expect(state.env).not.toHaveBeenCalled()

    const secret = screen.getByLabelText('JWT_SECRET_KEY', { exact: true })
    await expect.element(secret).toHaveAttribute('type', 'password')
    await secret.fill('abc123')
    await screen
      .getByLabelText('QA_ADMIN_EMAIL', { exact: true })
      .fill('qa@example.com')
    await screen
      .getByRole('switch', { name: 'Keep JWT_SECRET_KEY secret' })
      .click()
    await screen.getByRole('button', { name: 'Save and continue' }).click()
    expect(state.env).toHaveBeenCalledOnce()
    expect(state.env.mock.calls[0][0]).toEqual({
      runId: 7,
      values: {
        JWT_SECRET_KEY: { value: 'abc123', secret: false },
        QA_ADMIN_EMAIL: { value: 'qa@example.com', secret: false },
      },
    })
  })

  it('sends a saved value only once after a partial save', async () => {
    const { screen: s } = show({
      state: 'needs_input',
      proposal: proposed,
      missing_env: [
        { name: 'JWT_SECRET_KEY', description: '', secret: true },
        { name: 'QA_ADMIN_EMAIL', description: '', secret: false },
      ],
    })
    const screen = await s
    await screen
      .getByLabelText('JWT_SECRET_KEY', { exact: true })
      .fill('abc123')
    await screen.getByRole('button', { name: 'Save and continue' }).click()
    expect(state.env.mock.calls[0][0].values).toEqual({
      JWT_SECRET_KEY: { value: 'abc123', secret: true },
    })
    // the server saved it; QA_ADMIN_EMAIL is still missing
    state.env.mock.calls[0][1].onSuccess({
      ...base,
      state: 'needs_input',
      missing_env: [{ name: 'QA_ADMIN_EMAIL', description: '', secret: false }],
    })
    await expect
      .element(screen.getByLabelText('JWT_SECRET_KEY', { exact: true }))
      .toHaveValue('')
    await screen
      .getByLabelText('QA_ADMIN_EMAIL', { exact: true })
      .fill('qa@example.com')
    await screen.getByRole('button', { name: 'Save and continue' }).click()
    expect(state.env.mock.calls[1][0]).toEqual({
      runId: 7,
      values: { QA_ADMIN_EMAIL: { value: 'qa@example.com', secret: false } },
    })
  })

  it('lists the saved values the proof will use and continues on confirm', async () => {
    const { screen: s } = show({
      state: 'needs_input',
      proposal: proposed,
      confirm_env: [
        {
          name: 'JWT_SECRET_KEY',
          secret: true,
          used_in: ['services.api.env'],
        },
        {
          name: 'QA_ADMIN_EMAIL',
          secret: false,
          used_in: ['init[0]', 'qa.login'],
        },
      ],
      missing_env: [{ name: 'SMTP_PASSWORD', description: '', secret: true }],
    })
    const screen = await s
    await expect
      .element(screen.getByText('Awak will use these saved values'))
      .toBeVisible()
    const jwt = screen
      .getByRole('listitem')
      .filter({ hasText: 'JWT_SECRET_KEY' })
    await expect.element(jwt).toHaveTextContent(/Secret/)
    await expect.element(jwt).toHaveTextContent(/Used in\s*services\.api\.env/)
    const email = screen
      .getByRole('listitem')
      .filter({ hasText: 'QA_ADMIN_EMAIL' })
    await expect.element(email).toHaveTextContent(/init\[0\]\s*qa\.login/)
    // the missing-value form is there too
    await expect
      .element(screen.getByLabelText('SMTP_PASSWORD', { exact: true }))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Continue', exact: true }).click()
    expect(state.env).toHaveBeenCalledOnce()
    expect(state.env.mock.calls[0][0]).toEqual({
      runId: 7,
      values: {},
      confirm: true,
    })
  })

  it('shows the proof when ready and approves with Browser QA', async () => {
    const { screen: s } = show({
      state: 'ready',
      active: false,
      proposal: proposed,
      steps,
      screenshot: true,
      resources: {
        compose: [
          { service: 'api', container: 'postgres', mem_mb: 48.2, cpu_pct: 0.4 },
        ],
        processes: [{ name: 'web', rss_mb: 512 }],
        total_mb: 560.2,
      },
    })
    const screen = await s
    await expect
      .element(screen.getByRole('img', { name: /Screenshot of the app/ }))
      .toBeInTheDocument()
    await expect.element(screen.getByText('560 MB in total')).toBeVisible()
    await expect.element(screen.getByText('api · postgres')).toBeVisible()
    await expect.element(screen.getByText('Proposed runbook')).toBeVisible()
    await expect
      .element(screen.getByText('pnpm exec next dev --port {port}'))
      .toBeVisible()
    const browser = screen.getByRole('checkbox', {
      name: 'Switch QA to Browser',
    })
    await expect.element(browser).toBeChecked()
    await screen.getByRole('button', { name: 'Approve runbook' }).click()
    expect(state.approve.mock.calls[0][0]).toEqual({
      runId: 7,
      qaMode: 'browser',
    })

    await browser.click()
    await screen.getByRole('button', { name: 'Approve runbook' }).click()
    expect(state.approve.mock.calls[1][0]).toEqual({ runId: 7, qaMode: null })
  })

  it('shows the error and offers Try again when the run failed', async () => {
    const { screen: s, onRetry } = show({
      state: 'failed',
      active: false,
      round: 3,
      proposal: proposed,
      steps,
      error: 'Round 3/3: a process service did not start',
    })
    const screen = await s
    await expect
      .element(screen.getByText('Round 3/3: a process service did not start'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('listitem').filter({ hasText: 'Proving' }))
      .toHaveTextContent(/failed here/)
    await screen.getByRole('button', { name: 'Try again' }).click()
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('collapses a superseded run with its own label', async () => {
    const { screen: s } = show({
      state: 'superseded',
      active: false,
      proposal: proposed,
      steps,
    })
    const screen = await s
    await expect
      .element(screen.getByText(/Replaced by a newer setup run/))
      .toBeVisible()
    expect(screen.getByRole('button').elements()).toHaveLength(0)
  })

  it('collapses an approved run to a confirmation', async () => {
    const { screen: s } = show({
      state: 'approved',
      active: false,
      proposal: proposed,
      steps,
    })
    const screen = await s
    await expect
      .element(
        screen.getByText('Runbook approved from Configure automatically.')
      )
      .toBeVisible()
    expect(screen.getByText('install web').elements()).toHaveLength(0)
  })

  it.each<Partial<SetupRun>>([
    { state: 'proving', steps },
    {
      state: 'needs_input',
      missing_env: [{ name: 'JWT_SECRET_KEY', description: '', secret: true }],
    },
    {
      state: 'needs_input',
      confirm_env: [
        { name: 'JWT_SECRET_KEY', secret: true, used_in: ['qa.env'] },
      ],
    },
    { state: 'ready', active: false, steps },
    { state: 'failed', active: false, error: 'boom' },
  ])('gives members no admin controls ($state)', async (run) => {
    const screen = await show(
      { ...run, proposal: proposed },
      { canEdit: false }
    ).screen
    await expect.element(screen.getByText('Setup Assistant')).toBeVisible()
    expect(screen.getByRole('button').elements()).toHaveLength(0)
    expect(screen.getByRole('textbox').elements()).toHaveLength(0)
    expect(screen.getByRole('checkbox').elements()).toHaveLength(0)
    if (run.state === 'needs_input')
      await expect
        .element(screen.getByText(/Waiting for a project admin/))
        .toBeVisible()
    if (run.confirm_env?.length)
      await expect
        .element(screen.getByText(/let Awak use these saved values/))
        .toBeVisible()
  })

  it('does not offer Browser QA when the project already uses it', async () => {
    const screen = await render(
      <QueryClientProvider client={new QueryClient()}>
        <SetupAssistant
          slug='pf'
          run={{ ...base, state: 'ready', active: false, proposal: proposed }}
          canEdit
          qaMode='browser'
          onRetry={() => {}}
          retrying={false}
        />
      </QueryClientProvider>
    )
    expect(screen.getByRole('checkbox').elements()).toHaveLength(0)
    await screen.getByRole('button', { name: 'Approve runbook' }).click()
    expect(state.approve.mock.calls[0][0]).toEqual({ runId: 7, qaMode: null })
  })
})
