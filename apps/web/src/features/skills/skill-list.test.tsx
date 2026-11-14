import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { Library } from '@/lib/kemudi-ai/skills'
import { impeccable, notes } from './fixtures'
import { SkillList } from './skill-list'

const state = vi.hoisted(() => ({
  library: null as null | {
    data?: Library
    isPending: boolean
    isError: boolean
    refetch: () => void
  },
  mutate: vi.fn(),
}))

vi.mock('@/lib/kemudi-ai/skills', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/skills')>()),
  useSkillLibrary: () => state.library,
  useSetSkillEnabled: () => ({ mutate: state.mutate, isPending: false }),
}))

const limits = {
  max_bytes: 2097152,
  max_files: 200,
  max_upload_bytes: 4194304,
  description_max: 1024,
  description_agent_max: 300,
}

function loaded(skills: Library['skills']) {
  state.library = {
    data: { skills, limits },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  }
}

beforeEach(() => {
  state.mutate.mockReset()
})

describe('SkillList', () => {
  it('lists every skill with source, version, scan, licence and use', async () => {
    loaded([impeccable, notes])
    const onOpen = vi.fn()
    const screen = await render(<SkillList onOpen={onOpen} />)
    await expect.element(screen.getByText('2 skills')).toBeVisible()
    await expect
      .element(screen.getByText('Impeccable', { exact: true }))
      .toBeVisible()
    await expect.element(screen.getByText('Built in')).toBeVisible()
    await expect.element(screen.getByText('Licence Apache-2.0')).toBeVisible()
    await expect.element(screen.getByText('Used by 1 role')).toBeVisible()
    await expect.element(screen.getByText('Scan: low')).toBeVisible()
    await expect.element(screen.getByText('v2')).toBeVisible()
    await expect.element(screen.getByText('Licence unspecified')).toBeVisible()
    await expect.element(screen.getByText('Scan: high')).toBeVisible()
    await expect.element(screen.getByText('Not assigned')).toBeVisible()
    await screen.getByText('Impeccable', { exact: true }).click()
    expect(onOpen).toHaveBeenCalledWith('impeccable')
  })

  it('disables a skill with the switch and blocks enabling a high finding', async () => {
    loaded([impeccable, notes])
    const screen = await render(<SkillList onOpen={vi.fn()} />)
    const on = screen.getByRole('switch', { name: 'Enable Impeccable' })
    await expect.element(on).toBeChecked()
    await on.click()
    expect(state.mutate).toHaveBeenCalledWith(
      { slug: 'impeccable', enabled: false },
      expect.anything()
    )
    await expect
      .element(screen.getByRole('switch', { name: 'Enable release-notes' }))
      .toBeDisabled()
  })

  it('shows the empty state', async () => {
    loaded([])
    const screen = await render(<SkillList onOpen={vi.fn()} />)
    await expect.element(screen.getByText('No skills yet')).toBeVisible()
  })

  it('offers a retry when loading fails', async () => {
    state.library = {
      isPending: false,
      isError: true,
      refetch: vi.fn(),
    }
    const screen = await render(<SkillList onOpen={vi.fn()} />)
    await screen.getByRole('button', { name: 'Try again' }).click()
    expect(state.library.refetch).toHaveBeenCalled()
  })
})
