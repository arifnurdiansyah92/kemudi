import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { SkillDetail } from '@/lib/kemudi-ai/skills'
import { Sheet, SheetContent } from '@/components/ui/sheet'
import { apiError, detailOf, impeccable, notes } from './fixtures'
import { DetailBody } from './skill-detail'

/** DetailBody lives inside the sheet (its title needs the dialog). */
function inSheet(
  skill: SkillDetail,
  { onDeleted = vi.fn(), onNewVersion = vi.fn() } = {}
) {
  return render(
    <Sheet open>
      <SheetContent>
        <DetailBody
          skill={skill}
          onDeleted={onDeleted}
          onNewVersion={onNewVersion}
        />
      </SheetContent>
    </Sheet>
  )
}

const state = vi.hoisted(() => ({
  deleteMutate: vi.fn(),
  fileArgs: [] as unknown[][],
}))

vi.mock('@/lib/kemudi-ai/skills', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/skills')>()),
  useSetSkillEnabled: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteSkill: () => ({ mutate: state.deleteMutate, isPending: false }),
  useSkillFile: (...args: unknown[]) => {
    state.fileArgs.push(args)
    const path = args[2] as string | null
    return path
      ? {
          data: { path, size: 40, text: 'Use short sentences.' },
          isError: false,
        }
      : { data: undefined, isError: false }
  },
}))

beforeEach(() => {
  state.deleteMutate.mockReset()
  state.fileArgs = []
})

describe('DetailBody', () => {
  it('renders SKILL.md without unsafe links, plus warnings', async () => {
    const screen = await inSheet(detailOf(notes))
    await expect
      .element(screen.getByRole('heading', { name: 'How to' }))
      .toBeVisible()
    await expect.element(screen.getByText('the guide')).toBeVisible()
    expect(screen.container.querySelectorAll('a')).toHaveLength(0)
    await expect
      .element(screen.getByText(/No licence is stated in this skill/))
      .toBeVisible()
    await expect
      .element(
        screen.getByText(/has a high scan finding, so it can't be enabled/)
      )
      .toBeVisible()
  })

  it('lists findings by severity and versions', async () => {
    const screen = await inSheet(detailOf(notes))
    await screen.getByRole('tab', { name: /Findings/ }).click()
    await expect
      .element(screen.getByText('Pipes a download into a shell'))
      .toBeVisible()
    await expect
      .element(screen.getByText('High', { exact: true }))
      .toBeVisible()
    await screen.getByRole('tab', { name: /Versions/ }).click()
    await expect
      .element(screen.getByText('Current', { exact: true }))
      .toBeVisible()
    await expect.element(screen.getByText('aaaaaaaaaaaa')).toBeVisible()
  })

  it('shows a text file and says binaries are not shown', async () => {
    const screen = await inSheet(detailOf(notes))
    await screen.getByRole('tab', { name: /Files/ }).click()
    await expect
      .element(screen.getByText('Choose a file to view it.'))
      .toBeVisible()
    await screen.getByRole('button', { name: /reference\/style\.md/ }).click()
    await expect.element(screen.getByText('Use short sentences.')).toBeVisible()
    expect(state.fileArgs[state.fileArgs.length - 1]).toEqual([
      'release-notes',
      2,
      'reference/style.md',
    ])
    await screen.getByRole('button', { name: /assets\/logo\.png/ }).click()
    await expect
      .element(screen.getByText(/Binary file, .*Not shown\./))
      .toBeVisible()
  })

  it('deletes a local skill after confirming, and names the roles that block it', async () => {
    const onDeleted = vi.fn()
    const onNewVersion = vi.fn()
    const screen = await inSheet(detailOf(notes), { onDeleted, onNewVersion })
    await screen.getByRole('button', { name: 'New version' }).click()
    expect(onNewVersion).toHaveBeenCalled()
    await screen.getByRole('button', { name: 'Delete' }).click()
    await expect
      .element(screen.getByText('Delete release-notes?'))
      .toBeVisible()
    state.deleteMutate.mockImplementation((_slug, opts) =>
      opts.onError(
        apiError(409, {
          message: 'remove the skill from these roles first',
          problems: [],
          code: 'in_use',
          used_by: [{ project: 'playfast', role: 'PF-BE', role_id: 4 }],
        })
      )
    )
    await screen
      .getByRole('alertdialog')
      .getByRole('button', { name: 'Delete' })
      .click()
    expect(state.deleteMutate).toHaveBeenCalledWith(
      'release-notes',
      expect.anything()
    )
    expect(onDeleted).not.toHaveBeenCalled()
  })

  it('offers no delete or new version for a built-in skill', async () => {
    const screen = await inSheet(detailOf(impeccable))
    await expect.element(screen.getByText('Licence Apache-2.0')).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Delete' }).elements()
    ).toHaveLength(0)
    expect(
      screen.getByRole('button', { name: 'New version' }).elements()
    ).toHaveLength(0)
    await screen.getByRole('tab', { name: /Used by/ }).click()
    await expect.element(screen.getByText('PF-FE')).toBeVisible()
  })
})
