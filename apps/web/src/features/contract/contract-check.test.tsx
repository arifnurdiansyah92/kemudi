import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { CrCheck, TicketChecks } from '@/lib/kemudi-ai/queries'
import { api } from '@/lib/taiga/client'
import type { Project } from '@/lib/taiga/types'
import { ContractCheck } from './contract-check'

const check: CrCheck = {
  id: 5,
  ticket_kind: 'userstory',
  ticket_ref: 12,
  subject: 'Export laporan',
  baseline_number: 2,
  label: 'cr_candidate',
  reasoning: 'Export is not in the baseline.',
  clause: 'B2: Daily report',
  cited: [{ ref: 'B2', title: 'Daily report', clauses: ['S2: Laporan'] }],
  question: null,
  effort_days: { backend: 1.5, qa: 0.5 },
  effort_total_days: 2,
  price_idr: null,
  model: 'deepseek-flash',
  checked_by: 'pm (1)',
  checked_at: '2026-11-14T03:00:00Z',
  verdict: null,
  corrected_label: null,
  verdict_note: '',
  decided_by: null,
  decided_at: null,
}

function serve(data: TicketChecks) {
  return vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url === '/projects/demo/cr-checks/userstory/12') return { data }
    throw new Error(`unexpected GET ${url}`)
  })
}

async function renderCheck({ admin = true } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const project = { id: 1, slug: 'demo', i_am_admin: admin } as Project
  const rootRoute = createRootRoute({
    component: () => (
      <ContractCheck project={project} kind='userstory' itemRef={12} />
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return await render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

describe('ContractCheck', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('points admins at the Contract page without an approved baseline', async () => {
    serve({ baseline: null, show_prices: false, checks: [] })
    const screen = await renderCheck()
    await expect
      .element(screen.getByText(/no approved contract baseline/))
      .toBeVisible()
    await expect
      .element(screen.getByRole('link', { name: 'Set up the contract' }))
      .toHaveAttribute('href', '/p/demo/contract')
  })

  it('is hidden for members without an approved baseline', async () => {
    const get = serve({ baseline: null, show_prices: false, checks: [] })
    const screen = await renderCheck({ admin: false })
    await expect.poll(() => get.mock.calls.length).toBeGreaterThan(0)
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.container.textContent).toBe('')
  })

  it('runs a check for an admin', async () => {
    serve({ baseline: { number: 2 }, show_prices: false, checks: [] })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: check })
    const screen = await renderCheck()
    await expect.element(screen.getByText('Not checked yet.')).toBeVisible()
    await screen.getByRole('button', { name: 'Check against contract' }).click()
    expect(post).toHaveBeenCalledWith(
      '/projects/demo/cr-check',
      { kind: 'userstory', ref: 12 },
      expect.anything()
    )
  })

  it('shows the result with indicative person-days and no price', async () => {
    serve({ baseline: { number: 2 }, show_prices: false, checks: [check] })
    const screen = await renderCheck()
    await expect.element(screen.getByText('CR candidate')).toBeVisible()
    await expect
      .element(screen.getByText('Export is not in the baseline.'))
      .toBeVisible()
    await expect.element(screen.getByText('Daily report')).toBeVisible()
    await expect.element(screen.getByText('indicative')).toBeVisible()
    await expect.element(screen.getByText('2 person-days')).toBeVisible()
    expect(screen.container.textContent).not.toContain('Rp')
    await expect
      .element(screen.getByRole('button', { name: 'Check again' }))
      .toBeVisible()
  })

  it('shows the price when the project enables it', async () => {
    serve({
      baseline: { number: 2 },
      show_prices: true,
      checks: [{ ...check, price_idr: 2_500_000 }],
    })
    const screen = await renderCheck()
    await expect
      .element(screen.getByText(/2\.500\.000|2,500,000/))
      .toBeVisible()
  })

  it('records a disagreement with a corrected label', async () => {
    serve({ baseline: { number: 2 }, show_prices: false, checks: [check] })
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: { ...check, verdict: 'disagree' } })
    const screen = await renderCheck()
    await screen.getByRole('button', { name: 'Disagree' }).click()
    await screen.getByRole('radio', { name: 'In baseline' }).click()
    await screen.getByLabelText('Note').fill('Warranty fix')
    await screen.getByRole('button', { name: 'Save verdict' }).click()
    expect(post).toHaveBeenCalledWith(
      '/projects/demo/cr-checks/5/verdict',
      {
        verdict: 'disagree',
        corrected_label: 'in_baseline',
        note: 'Warranty fix',
      },
      expect.anything()
    )
  })

  it('offers no run or verdict buttons to members', async () => {
    serve({ baseline: { number: 2 }, show_prices: false, checks: [check] })
    const screen = await renderCheck({ admin: false })
    await expect.element(screen.getByText('CR candidate')).toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Agree' }))
      .not.toBeInTheDocument()
    await expect
      .element(screen.getByRole('button', { name: 'Check again' }))
      .not.toBeInTheDocument()
  })
})
