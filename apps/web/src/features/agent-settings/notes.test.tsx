import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { AgentNote } from '@/lib/kemudi-ai/agent'
import { AgentNotes } from './notes'

const state = vi.hoisted(() => ({
  notes: [] as AgentNote[],
  remove: vi.fn(),
}))

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useAgentNotes: () => ({
    isPending: false,
    isError: false,
    data: state.notes,
  }),
  useDeleteAgentNote: () => ({ mutate: state.remove, isPending: false }),
}))

function note(over: Partial<AgentNote>): AgentNote {
  return {
    id: 1,
    repo_id: 4,
    repo: 'web',
    text: 'tsc needs NODE_OPTIONS=--max-old-space-size=6144',
    job_id: 12,
    at: '2026-11-14T03:00:00Z',
    ...over,
  }
}

const notes: AgentNote[] = [
  note({ id: 7 }),
  note({
    id: 6,
    repo_id: null,
    repo: '',
    text: 'The seed script must run before the API starts',
    at: null,
  }),
]

beforeEach(() => {
  state.remove.mockReset()
  state.notes = notes
})

describe('AgentNotes', () => {
  it('lists each note with its repo as a badge', async () => {
    const screen = await render(<AgentNotes slug='pf' canEdit />)
    await expect
      .element(
        screen.getByText('tsc needs NODE_OPTIONS=--max-old-space-size=6144')
      )
      .toBeVisible()
    await expect.element(screen.getByText('web', { exact: true })).toBeVisible()
    await expect
      .element(
        screen.getByText('The seed script must run before the API starts')
      )
      .toBeVisible()
    // The second note names no repo: one badge, not two.
    expect(
      screen.container.querySelectorAll('[data-slot="badge"]')
    ).toHaveLength(1)
  })

  it('says when there are no notes yet', async () => {
    state.notes = []
    const screen = await render(<AgentNotes slug='pf' canEdit />)
    await expect
      .element(screen.getByText(/No notes yet\. They appear after Awak works/))
      .toBeVisible()
    expect(screen.getByRole('listitem').elements()).toHaveLength(0)
  })

  it('deletes a note once the admin confirms', async () => {
    const screen = await render(<AgentNotes slug='pf' canEdit />)
    await screen.getByRole('button', { name: 'Delete note' }).first().click()
    const dialog = screen.getByRole('alertdialog')
    await expect.element(dialog).toBeVisible()
    expect(state.remove).not.toHaveBeenCalled()
    await dialog.getByRole('button', { name: 'Delete' }).click()
    expect(state.remove).toHaveBeenCalledWith(7, expect.anything())
  })

  it('offers no delete to a member who is not an admin', async () => {
    const screen = await render(<AgentNotes slug='pf' canEdit={false} />)
    await expect
      .element(
        screen.getByText('tsc needs NODE_OPTIONS=--max-old-space-size=6144')
      )
      .toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Delete note' }).elements()
    ).toHaveLength(0)
  })

  it('shows the first 8 notes until asked for all', async () => {
    state.notes = Array.from({ length: 10 }, (_, i) =>
      note({ id: 100 - i, text: `Note number ${i + 1}` })
    )
    const screen = await render(<AgentNotes slug='pf' canEdit />)
    expect(screen.getByRole('listitem').elements()).toHaveLength(8)
    await screen.getByRole('button', { name: 'Show all 10 notes' }).click()
    expect(screen.getByRole('listitem').elements()).toHaveLength(10)
    await expect
      .element(screen.getByRole('button', { name: 'Show less' }))
      .toBeVisible()
  })
})
