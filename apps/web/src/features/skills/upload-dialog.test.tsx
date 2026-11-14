import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { userEvent } from 'vitest/browser'
import { apiError, detailOf, notes } from './fixtures'
import { UploadDialog } from './upload-dialog'

const state = vi.hoisted(() => ({ mutate: vi.fn() }))

vi.mock('@/lib/kemudi-ai/skills', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/skills')>()),
  useUploadSkill: () => ({
    mutate: state.mutate,
    isPending: false,
    reset: vi.fn(),
  }),
}))

beforeEach(() => {
  state.mutate.mockReset()
})

function zipFile() {
  // Contents don't matter: the upload hook is mocked.
  return new File([new Uint8Array([0x50, 0x4b, 3, 4])], 'notes.zip', {
    type: 'application/zip',
  })
}

async function open(onOpenSkill = vi.fn()) {
  const screen = await render(
    <UploadDialog open onOpenChange={vi.fn()} onOpenSkill={onOpenSkill} />
  )
  await userEvent.upload(
    screen.getByLabelText('Drop a file here or choose one'),
    zipFile()
  )
  await expect.element(screen.getByText('notes.zip')).toBeVisible()
  return screen
}

describe('UploadDialog', () => {
  it('uploads and shows the scan result', async () => {
    const onOpenSkill = vi.fn()
    state.mutate.mockImplementation((_vars, opts) =>
      opts.onSuccess({
        skill: { ...detailOf(notes), version: 1 },
        created: true,
        unchanged: false,
        disabled: false,
        warnings: [],
      })
    )
    const screen = await open(onOpenSkill)
    await screen.getByRole('button', { name: 'Upload', exact: true }).click()
    expect(state.mutate.mock.calls[0][0]).toMatchObject({ replace: false })
    expect(state.mutate.mock.calls[0][0].file.name).toBe('notes.zip')
    await expect
      .element(screen.getByText('release-notes uploaded as version 1'))
      .toBeVisible()
    await expect
      .element(screen.getByText('The scan found 2 things to review.'))
      .toBeVisible()
    await expect.element(screen.getByText('Scan: high')).toBeVisible()
    await screen.getByRole('button', { name: 'Open skill' }).click()
    expect(onOpenSkill).toHaveBeenCalledWith('release-notes')
  })

  it('lists the problems of a refused archive', async () => {
    state.mutate.mockImplementation((_vars, opts) =>
      opts.onError(
        apiError(422, {
          message: 'the upload was refused',
          problems: ["'notes/link.md': symlinks are not allowed"],
        })
      )
    )
    const screen = await open()
    await screen.getByRole('button', { name: 'Upload', exact: true }).click()
    await expect
      .element(screen.getByText('The upload was refused'))
      .toBeVisible()
    await expect
      .element(screen.getByText("'notes/link.md': symlinks are not allowed"))
      .toBeVisible()
  })

  it('offers to add a new version when a local skill has the name', async () => {
    state.mutate.mockImplementationOnce((_vars, opts) =>
      opts.onError(
        apiError(409, {
          message: 'a local skill named release-notes exists',
          problems: [],
          code: 'exists',
          slug: 'release-notes',
          source: 'local',
          version: 2,
        })
      )
    )
    const screen = await open()
    await screen.getByRole('button', { name: 'Upload', exact: true }).click()
    await expect
      .element(
        screen.getByText(
          'A local skill named release-notes already exists (version 2).'
        )
      )
      .toBeVisible()
    state.mutate.mockImplementationOnce((_vars, opts) =>
      opts.onSuccess({
        skill: { ...detailOf(notes), version: 3 },
        created: false,
        unchanged: false,
        disabled: false,
        warnings: [],
      })
    )
    await screen.getByRole('button', { name: 'Add as new version' }).click()
    expect(state.mutate.mock.calls[1][0]).toMatchObject({ replace: true })
    await expect
      .element(screen.getByText('release-notes is now at version 3'))
      .toBeVisible()
  })

  it('says which roles get the new version, and asks before a worse scan goes live', async () => {
    const usedBy = [{ project: 'playfast', role: 'PF-FE', role_id: 3 }]
    state.mutate.mockImplementationOnce((_vars, opts) =>
      opts.onError(
        apiError(409, {
          message: 'a local skill named release-notes exists',
          problems: [],
          code: 'exists',
          slug: 'release-notes',
          source: 'local',
          version: 2,
          enabled: true,
          used_by: usedBy,
        })
      )
    )
    const screen = await open()
    await screen.getByRole('button', { name: 'Upload', exact: true }).click()
    await expect
      .element(screen.getByText('1 role will get it on its next run.'))
      .toBeVisible()
    state.mutate.mockImplementationOnce((_vars, opts) =>
      opts.onError(
        apiError(409, {
          message: 'worse scan',
          problems: ['SKILL.md:3 network_url'],
          code: 'findings_rise',
          slug: 'release-notes',
          worst: 'low',
          previous: '',
          findings: [
            {
              rule: 'network_url',
              severity: 'low',
              path: 'SKILL.md',
              line: 3,
              excerpt: 'https://example.com',
            },
          ],
          used_by: usedBy,
        })
      )
    )
    await screen.getByRole('button', { name: 'Add as new version' }).click()
    await expect
      .element(
        screen.getByText(
          "This version's scan (low) is worse than the current version's (clean), and 1 role will get it on its next run."
        )
      )
      .toBeVisible()
    await expect.element(screen.getByText('Network URL')).toBeVisible()
    state.mutate.mockImplementationOnce((_vars, opts) =>
      opts.onSuccess({
        skill: { ...detailOf(notes), version: 3 },
        created: false,
        unchanged: false,
        disabled: false,
        warnings: [],
      })
    )
    await screen
      .getByRole('button', { name: 'Use this version anyway' })
      .click()
    expect(state.mutate.mock.calls[1][0]).toMatchObject({
      replace: true,
      acceptFindings: false,
    })
    expect(state.mutate.mock.calls[2][0]).toMatchObject({
      replace: true,
      acceptFindings: true,
    })
    await expect
      .element(screen.getByText('release-notes is now at version 3'))
      .toBeVisible()
  })

  it('explains a clash with a built-in skill', async () => {
    state.mutate.mockImplementation((_vars, opts) =>
      opts.onError(
        apiError(409, {
          message: 'impeccable is a builtin skill',
          problems: [],
          code: 'not_local',
          slug: 'impeccable',
        })
      )
    )
    const screen = await open()
    await screen.getByRole('button', { name: 'Upload', exact: true }).click()
    await expect
      .element(
        screen.getByText(/impeccable is a built-in or marketplace skill/)
      )
      .toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Add as new version' }).elements()
    ).toHaveLength(0)
  })
})
