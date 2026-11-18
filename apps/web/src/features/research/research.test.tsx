import { type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { useAuthStore } from '@/stores/auth-store'
import type {
  ProductAgents,
  ProductRun,
  ProductRunSummary,
} from '@/lib/kemudi-ai/product'
import { api } from '@/lib/taiga/client'
import { Research } from './index'

const mocks = vi.hoisted(() => ({
  admin: false,
  search: {} as { run?: number },
  navigate: vi.fn(),
}))

vi.mock('@tanstack/react-router', () => ({
  Link: ({
    children,
    search,
    className,
    'aria-current': current,
  }: {
    children: ReactNode
    search?: { run?: number }
    className?: string
    'aria-current'?: 'true'
  }) => (
    <a
      href={search?.run ? `?run=${search.run}` : '#'}
      className={className}
      aria-current={current}
    >
      {children}
    </a>
  ),
  useNavigate: () => mocks.navigate,
  useSearch: () => mocks.search,
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

const agents: ProductAgents = {
  web: true,
  agents: [
    { kind: 'competitor', needs_web: true },
    { kind: 'features', needs_web: false },
    { kind: 'report', needs_web: false },
    { kind: 'custom', needs_web: true },
  ],
}

function summary(over: Partial<ProductRunSummary>): ProductRunSummary {
  return {
    id: 1,
    kind: 'competitor',
    title: 'Competitors of Demo',
    brief: '',
    lang: 'en',
    status: 'done',
    stage: '',
    error: '',
    web: true,
    created_by: 'sari',
    created_at: '2026-11-17T08:00:00Z',
    started_at: '2026-11-17T08:00:05Z',
    finished_at: '2026-11-17T08:06:00Z',
    options: {},
    ...over,
  }
}

const runs: ProductRunSummary[] = [
  summary({
    id: 5,
    kind: 'features',
    title: 'What to build next',
    brief: 'Focus on onboarding',
    options: { based_on: 3 },
  }),
  summary({
    id: 4,
    kind: 'report',
    title: 'Delivery in the last 30 days',
    status: 'running',
    stage: 'data',
    finished_at: null,
    options: { days: 30 },
  }),
  summary({ id: 3, title: 'Competitors of Demo' }),
  summary({
    id: 2,
    kind: 'custom',
    title: 'Market size in Indonesia',
    status: 'failed',
    error: 'The model ran out of budget',
  }),
]

const featuresRun: ProductRun = {
  ...runs[0],
  report: '# What to build next\n\nThree ideas, strongest first.',
  suggestions: [
    {
      title: 'Guided setup',
      problem: 'New teams stall on the first project.',
      proposal: 'Add a checklist that walks through setup.',
      value: 'More teams reach their first story.',
      effort: 'M',
      area: 'web',
      evidence: 'Two competitors have one.',
    },
    {
      title: 'Bulk import',
      problem: 'Moving from a spreadsheet is manual.',
      proposal: 'Import stories from CSV.',
      value: 'Faster migration.',
      effort: 'L',
      area: 'both',
      evidence: 'Backlog #41.',
    },
  ],
  sources: [{ title: 'Rival pricing', url: 'https://rival.example/pricing' }],
}

function serve(over: { agents?: ProductAgents; run?: ProductRun } = {}) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url.endsWith('/product/agents')) return { data: over.agents ?? agents }
    if (url.endsWith('/product/runs')) return { data: { runs } }
    if (over.run && url.endsWith(`/product/runs/${over.run.id}`))
      return { data: over.run }
    throw new Error(`unexpected GET ${url}`)
  })
}

async function renderResearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return await render(
    <QueryClientProvider client={client}>
      <Research />
    </QueryClientProvider>
  )
}

/** Picks an agent card; the run list repeats the same labels. */
const pick = (
  screen: Awaited<ReturnType<typeof renderResearch>>,
  name: string
) =>
  screen
    .getByRole('group', { name: 'Agent' })
    .getByText(name, { exact: true })
    .click()

describe('Research', () => {
  beforeEach(() => {
    mocks.admin = false
    mocks.search = {}
    mocks.navigate.mockReset()
    sessionStorage.clear()
    useAuthStore.setState({
      session: {
        token: 'token',
        refresh: 'refresh',
        user: { id: 7, username: 'budi' },
      } as never,
    })
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('lists the four agents and the runs with their status', async () => {
    const get = serve()
    const screen = await renderResearch()

    for (const name of [
      'Competitor research',
      'Feature suggestions',
      'Project data report',
      'Custom research',
    ])
      await expect
        .element(screen.getByRole('radio', { name }))
        .toBeInTheDocument()

    await expect
      .element(screen.getByRole('link', { name: /What to build next/ }))
      .toHaveAttribute('href', '?run=5')
    await expect
      .element(screen.getByRole('link', { name: /Market size in Indonesia/ }))
      .toHaveTextContent('Failed')
    // A running run says what it is doing.
    await expect
      .element(
        screen.getByRole('link', { name: /Delivery in the last 30 days/ })
      )
      .toHaveTextContent('Fetching project data')
    // Web is available, so there is nothing to warn about.
    await expect
      .element(screen.getByText('No web research on this server'))
      .not.toBeInTheDocument()

    const listCall = get.mock.calls.find(([url]) =>
      url.endsWith('/product/runs')
    )
    expect(listCall?.[1]).toMatchObject({ params: { limit: 30 } })
  })

  it('starts a report run with its period and opens it', async () => {
    serve()
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        ...summary({ id: 9, kind: 'report', status: 'queued' }),
        report: '',
        suggestions: [],
        sources: [],
      },
    })

    const screen = await renderResearch()
    await pick(screen, 'Project data report')
    await screen.getByLabelText('Period').selectOptions('7')
    await screen.getByLabelText('Brief (optional)').fill('  For the client  ')
    await screen.getByRole('button', { name: 'Start research' }).click()

    await vi.waitFor(() => expect(post).toHaveBeenCalledOnce())
    const [url, body] = post.mock.calls[0] as [string, unknown]
    expect(url).toBe('/projects/demo/product/runs')
    expect(body).toEqual({
      kind: 'report',
      brief: 'For the client',
      lang: 'en',
      options: { days: 7 },
    })
    await vi.waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith(
        expect.objectContaining({ search: { run: 9 } })
      )
    )
  })

  it('offers finished competitor runs as the basis of feature suggestions', async () => {
    serve()
    const post = vi.spyOn(api, 'post').mockResolvedValue({
      data: { ...featuresRun, id: 10, status: 'queued' },
    })

    const screen = await renderResearch()
    await pick(screen, 'Feature suggestions')
    await screen
      .getByLabelText('Based on competitor research')
      .selectOptions('3')
    await screen.getByRole('button', { name: 'Start research' }).click()

    await vi.waitFor(() => expect(post).toHaveBeenCalledOnce())
    expect(post.mock.calls[0][1]).toEqual({
      kind: 'features',
      brief: '',
      lang: 'en',
      options: { based_on: 3 },
    })
  })

  it('needs a brief of 10 characters for custom research', async () => {
    serve()
    const screen = await renderResearch()
    await pick(screen, 'Custom research')
    const start = screen.getByRole('button', { name: 'Start research' })
    await expect.element(start).toBeDisabled()
    await screen.getByLabelText('Brief').fill('too short')
    await expect.element(start).toBeDisabled()
    await screen.getByLabelText('Brief').fill('Size of the PM tool market')
    await expect.element(start).toBeEnabled()
  })

  it('says the result may be outdated when the server has no web research', async () => {
    serve({ agents: { ...agents, web: false } })
    const screen = await renderResearch()
    // Competitor research is picked first and needs the web.
    await expect
      .element(screen.getByText('No web research on this server'))
      .toBeVisible()
    await expect.element(screen.getByText(/may be out of date/)).toBeVisible()
    // It can still be started.
    await expect
      .element(screen.getByRole('button', { name: 'Start research' }))
      .toBeEnabled()

    // The data report does not use the web: no note.
    await pick(screen, 'Project data report')
    await expect
      .element(screen.getByText('No web research on this server'))
      .not.toBeInTheDocument()
  })

  it('shows a finished features run and hands the picked suggestions to Intake', async () => {
    mocks.search = { run: 5 }
    serve({ run: featuresRun })
    const screen = await renderResearch()

    await expect
      .element(
        screen.getByRole('heading', { name: 'What to build next' }).first()
      )
      .toBeVisible()
    await expect
      .element(screen.getByText('Three ideas, strongest first.'))
      .toBeVisible()
    await expect.element(screen.getByText('Focus on onboarding')).toBeVisible()
    await expect
      .element(screen.getByRole('link', { name: 'Rival pricing' }))
      .toHaveAttribute('rel', 'noopener noreferrer')
    await expect
      .element(screen.getByRole('link', { name: 'Rival pricing' }))
      .toHaveAttribute('target', '_blank')

    // Both suggestions start picked.
    await expect.element(screen.getByText('2 of 2 selected')).toBeVisible()
    await expect.element(screen.getByText('Medium effort')).toBeVisible()
    await expect
      .element(screen.getByText('Add a checklist that walks through setup.'))
      .toBeVisible()
    await screen.getByRole('checkbox', { name: 'Bulk import' }).click()
    await expect.element(screen.getByText('1 of 2 selected')).toBeVisible()
    await screen.getByRole('checkbox', { name: 'Bulk import' }).click()

    await screen.getByRole('button', { name: 'Send to Intake' }).click()

    expect(
      JSON.parse(sessionStorage.getItem('kemudi.intake.prefill')!)
    ).toEqual({
      slug: 'demo',
      text: [
        '1. Guided setup',
        'Problem: New teams stall on the first project.',
        'Proposal: Add a checklist that walks through setup.',
        '',
        '2. Bulk import',
        'Problem: Moving from a spreadsheet is manual.',
        'Proposal: Import stories from CSV.',
      ].join('\n'),
    })
    expect(mocks.navigate).toHaveBeenCalledWith({
      to: '/p/$slug/intake',
      params: { slug: 'demo' },
    })
  })

  it('sends only the suggestions left ticked', async () => {
    mocks.search = { run: 5 }
    serve({ run: featuresRun })
    const screen = await renderResearch()

    await screen.getByRole('checkbox', { name: 'Guided setup' }).click()
    await screen.getByRole('button', { name: 'Send to Intake' }).click()

    const { text } = JSON.parse(
      sessionStorage.getItem('kemudi.intake.prefill')!
    ) as { text: string }
    expect(text).toBe(
      '1. Bulk import\nProblem: Moving from a spreadsheet is manual.\nProposal: Import stories from CSV.'
    )
  })

  it('lets only an admin or the creator delete a run', async () => {
    mocks.search = { run: 5 }
    serve({ run: featuresRun })
    const del = vi.spyOn(api, 'delete').mockResolvedValue({ data: null })

    // budi is neither an admin nor the creator (sari).
    const stranger = await renderResearch()
    await expect
      .element(stranger.getByRole('button', { name: 'Copy Markdown' }))
      .toBeVisible()
    await expect
      .element(stranger.getByRole('button', { name: 'Download .md' }))
      .toBeVisible()
    await expect
      .element(stranger.getByRole('button', { name: 'Delete' }))
      .not.toBeInTheDocument()
    await stranger.unmount()

    useAuthStore.setState({
      session: {
        token: 'token',
        refresh: 'refresh',
        user: { id: 8, username: 'sari' },
      } as never,
    })
    const creator = await renderResearch()
    await creator.getByRole('button', { name: 'Delete' }).click()
    await expect
      .element(creator.getByText('Delete this research?'))
      .toBeVisible()
    await creator
      .getByRole('alertdialog')
      .getByRole('button', { name: 'Delete' })
      .click()

    await vi.waitFor(() => expect(del).toHaveBeenCalledOnce())
    expect(del.mock.calls[0][0]).toBe('/projects/demo/product/runs/5')
    // Back to the form once it is gone.
    await vi.waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith(
        expect.objectContaining({ search: { run: undefined } })
      )
    )
  })

  it('shows the stage of a running run and keeps an admin from deleting it', async () => {
    mocks.admin = true
    mocks.search = { run: 4 }
    serve({
      run: {
        ...runs[1],
        stage: 'writing',
        report: '',
        suggestions: [],
        sources: [],
      },
    })
    const screen = await renderResearch()

    await expect
      .element(screen.getByRole('status').getByText('Writing the report'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Delete' }))
      .toBeDisabled()
    await expect
      .element(screen.getByRole('button', { name: 'Copy Markdown' }))
      .not.toBeInTheDocument()
  })

  it('shows why a run failed', async () => {
    mocks.search = { run: 2 }
    serve({
      run: { ...runs[3], report: '', suggestions: [], sources: [] },
    })
    const screen = await renderResearch()

    await expect.element(screen.getByText('The research failed')).toBeVisible()
    await expect
      .element(screen.getByText('The model ran out of budget'))
      .toBeVisible()
  })

  it('invites a first run when there are none', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
      if (url.endsWith('/product/agents')) return { data: agents }
      if (url.endsWith('/product/runs')) return { data: { runs: [] } }
      throw new Error(`unexpected GET ${url}`)
    })
    const screen = await renderResearch()
    await expect.element(screen.getByText('No research yet')).toBeVisible()
  })
})
