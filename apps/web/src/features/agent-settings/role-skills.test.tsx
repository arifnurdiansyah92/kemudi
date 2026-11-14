import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type {
  RoleSkill,
  RoleTemplate,
  SkillCatalog,
  SkillOption,
} from '@/lib/kemudi-ai/agent'
import { RoleSkills } from './role-skills'

const state = vi.hoisted(() => ({
  catalog: null as null | {
    data?: SkillCatalog
    isPending: boolean
    isSuccess: boolean
    isError: boolean
  },
}))

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useSkillCatalog: () => state.catalog,
}))

const impeccable: SkillOption = {
  slug: 'impeccable',
  title: 'Impeccable',
  description: 'Design, critique and polish a frontend.',
  source: 'builtin',
  license: 'Apache-2.0',
  enabled: true,
  version: 1,
  scan_level: '',
}
const testing: SkillOption = {
  slug: 'api-testing',
  title: 'API testing',
  description: 'Contract tests for HTTP APIs.',
  source: 'local',
  license: '',
  enabled: true,
  version: 3,
  scan_level: 'medium',
}

function loaded(skills: SkillOption[]) {
  state.catalog = {
    data: {
      skills,
      template_defaults: {
        frontend: skills.some((s) => s.slug === 'impeccable')
          ? ['impeccable']
          : [],
        backend: [],
      },
    },
    isPending: false,
    isSuccess: true,
    isError: false,
  }
}

function renderSkills({
  value = [] as string[] | null,
  template = 'frontend' as RoleTemplate,
  details = [] as RoleSkill[],
  readOnly = false,
  onChange = vi.fn(),
} = {}) {
  return render(
    <RoleSkills
      value={value}
      onChange={onChange}
      template={template}
      details={details}
      readOnly={readOnly}
    />
  )
}

describe('RoleSkills', () => {
  it('shows chosen skills with their source, scan and licence, and removes one', async () => {
    loaded([impeccable, testing])
    const onChange = vi.fn()
    const screen = await renderSkills({
      value: ['impeccable', 'api-testing'],
      onChange,
    })
    await expect
      .element(screen.getByText('Impeccable', { exact: true }))
      .toBeVisible()
    await expect.element(screen.getByText('Built in')).toBeVisible()
    await expect.element(screen.getByText('Scan clean')).toBeVisible()
    await expect.element(screen.getByText('Licence Apache-2.0')).toBeVisible()
    await expect.element(screen.getByText('Local')).toBeVisible()
    await expect.element(screen.getByText('Scan: medium')).toBeVisible()
    await expect.element(screen.getByText('No licence stated')).toBeVisible()
    await screen.getByRole('button', { name: 'Remove Impeccable' }).click()
    expect(onChange).toHaveBeenCalledWith(['api-testing'])
  })

  it('adds a skill from the searchable picker', async () => {
    loaded([impeccable, testing])
    const onChange = vi.fn()
    const screen = await renderSkills({ value: [], onChange })
    await expect
      .element(
        screen.getByText('No skills. Awak works from the role prompt only.')
      )
      .toBeVisible()
    await screen.getByRole('button', { name: 'Add skill' }).click()
    await expect
      .element(screen.getByRole('option', { name: /Impeccable/ }))
      .toBeVisible()
    await screen
      .getByRole('combobox', { name: 'Search skills' })
      .fill('contract')
    expect(screen.getByRole('option').elements()).toHaveLength(1)
    await screen.getByRole('option', { name: /API testing/ }).click()
    expect(onChange).toHaveBeenCalledWith(['api-testing'])
  })

  it('says when nothing matches and when every skill is assigned', async () => {
    loaded([impeccable])
    const screen = await renderSkills({ value: [] })
    await screen.getByRole('button', { name: 'Add skill' }).click()
    await screen.getByRole('combobox', { name: 'Search skills' }).fill('zzz')
    await expect
      .element(screen.getByText('No skills match “zzz”.'))
      .toBeVisible()
  })

  it('says when every enabled skill is assigned', async () => {
    loaded([impeccable])
    const screen = await renderSkills({ value: ['impeccable'] })
    await screen.getByRole('button', { name: 'Add skill' }).click()
    await expect
      .element(screen.getByText('Every enabled skill is already assigned.'))
      .toBeVisible()
  })

  it('asks for an admin when no skills are installed', async () => {
    loaded([])
    const screen = await renderSkills({ value: [] })
    await expect
      .element(
        screen.getByText(
          'No skills are installed yet. Ask your Kemudi admin to install skills.'
        )
      )
      .toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Add skill' }).elements()
    ).toHaveLength(0)
    expect(
      screen.getByRole('button', { name: 'Reset to defaults' }).elements()
    ).toHaveLength(0)
  })

  it('warns about an assigned skill that is disabled or missing', async () => {
    loaded([impeccable])
    const onChange = vi.fn()
    const screen = await renderSkills({
      value: ['impeccable', 'api-testing', 'gone'],
      details: [
        { ...testing, enabled: false, status: 'disabled' },
        {
          slug: 'gone',
          title: 'gone',
          source: '',
          license: '',
          enabled: false,
          version: null,
          scan_level: '',
          status: 'missing',
        },
      ],
      onChange,
    })
    await expect
      .element(screen.getByText(/Disabled by a Kemudi admin/))
      .toBeVisible()
    await expect
      .element(screen.getByText('No longer installed. Awak skips it.'))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Remove gone' }).click()
    expect(onChange).toHaveBeenCalledWith(['impeccable', 'api-testing'])
  })

  it('resets to the template defaults and shows them', async () => {
    loaded([impeccable, testing])
    const onChange = vi.fn()
    const screen = await renderSkills({ value: ['api-testing'], onChange })
    await expect
      .element(screen.getByText('Frontend defaults: Impeccable'))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Reset to defaults' }).click()
    expect(onChange).toHaveBeenCalledWith(['impeccable'])
  })

  it('a template without defaults says so', async () => {
    loaded([impeccable, testing])
    const screen = await renderSkills({ value: [], template: 'backend' })
    await expect
      .element(screen.getByText('The Backend template has no default skills.'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Reset to defaults' }))
      .toBeDisabled()
  })

  it('a new role follows the template defaults until changed', async () => {
    loaded([impeccable])
    const screen = await renderSkills({ value: null })
    await expect
      .element(screen.getByText('Impeccable', { exact: true }))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Reset to defaults' }))
      .toBeDisabled()
  })

  it('read-only: rows without remove, add or reset', async () => {
    loaded([impeccable])
    const screen = await renderSkills({ value: ['impeccable'], readOnly: true })
    await expect
      .element(screen.getByText('Impeccable', { exact: true }))
      .toBeVisible()
    expect(screen.getByRole('button').elements()).toHaveLength(0)
  })
})
