import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { Job, MergeMode, StoryAgent } from '@/lib/kemudi-ai/agent'
import { api } from '@/lib/taiga/client'
import type { Item, Project } from '@/lib/taiga/types'
import { MergeAction } from './merge-action'

const job: Job = {
  id: 3,
  story_id: 7,
  story_ref: 21,
  branch: 'awak/21-login',
  state: 'passed',
  phase: 'qa',
  attempts: 1,
  cost_idr: 1200,
  repo_id: 1,
  role_id: 1,
  prompt_version: 'v1',
  merge_state: '',
  merged_sha: '',
  started_at: null,
  updated_at: null,
}

function agent(over: Partial<StoryAgent> = {}): StoryAgent {
  return {
    job,
    merge_mode: 'approve',
    can_merge: true,
    merge_state: '',
    merge_error: '',
    ...over,
  }
}

/** GET answers: the story's agent state (one per call, last repeats) and repos. */
function serve(states: StoryAgent[]) {
  let i = 0
  return vi.spyOn(api, 'get').mockImplementation(async (url: string) => {
    if (url.endsWith('/agent/stories/7'))
      return { data: states[Math.min(i++, states.length - 1)] }
    if (url.endsWith('/agent/repos'))
      return { data: { repos: [{ id: 1, default_branch: 'main' }] } }
    throw new Error(`unexpected GET ${url}`)
  })
}

async function renderMerge({
  admin = true,
  tags = [['awaiting-merge', null]] as Item['tags'],
} = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const project = { id: 1, slug: 'demo', i_am_admin: admin } as Project
  const story = { id: 7, ref: 21, tags } as Item
  return await render(
    <QueryClientProvider client={client}>
      <MergeAction project={project} story={story} />
    </QueryClientProvider>
  )
}

describe('MergeAction', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('is hidden without the awaiting-merge tag and asks nothing of the server', async () => {
    const get = serve([agent()])
    const screen = await renderMerge({ tags: [['area:web', null]] })
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.container.textContent).toBe('')
    expect(get).not.toHaveBeenCalled()
  })

  it('is hidden for a non-admin', async () => {
    serve([agent()])
    const screen = await renderMerge({ admin: false })
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.container.textContent).toBe('')
  })

  it.each<MergeMode>(['manual', 'auto'])(
    'is hidden when the merge mode is %s',
    async (mode) => {
      const get = serve([agent({ merge_mode: mode })])
      const screen = await renderMerge()
      await expect.poll(() => get.mock.calls.length).toBeGreaterThan(0)
      await new Promise((r) => setTimeout(r, 50))
      expect(screen.container.textContent).toBe('')
    }
  )

  it('confirms with both branches, then polls until the merge settles', async () => {
    serve([
      agent(),
      agent({ can_merge: false, merge_state: 'merging' }),
      agent({
        can_merge: false,
        merge_state: 'merged',
        job: { ...job, merge_state: 'merged', merged_sha: 'abc1234def' },
      }),
    ])
    const post = vi
      .spyOn(api, 'post')
      .mockResolvedValue({ data: { merge_state: 'requested' } })
    const screen = await renderMerge()

    await expect
      .element(screen.getByText(/Passed QA on awak\/21-login/))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Merge' }).click()
    const dialog = screen.getByRole('alertdialog')
    await expect
      .element(dialog.getByText(/merges awak\/21-login into main/))
      .toBeVisible()
    await dialog.getByRole('button', { name: 'Merge into main' }).click()

    expect(post).toHaveBeenCalledWith(
      '/projects/demo/agent/stories/7/merge',
      null,
      expect.anything()
    )
    await expect.element(screen.getByText(/Merging into main/)).toBeVisible()
    await expect
      .element(screen.getByText('Merged into main.'), { timeout: 8000 })
      .toBeVisible()
    await expect.element(screen.getByText('abc1234')).toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Merge' }))
      .not.toBeInTheDocument()
  }, 15_000)

  it('shows why a merge failed and offers a retry', async () => {
    serve([
      agent({
        merge_state: 'failed',
        merge_error: 'checks failed on abc12345',
      }),
    ])
    const screen = await renderMerge()
    await expect
      .element(screen.getByText('Merge failed: checks failed on abc12345'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Try again' }))
      .toBeVisible()
  })
})
