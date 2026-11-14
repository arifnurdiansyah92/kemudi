import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type {
  Marketplace,
  MarketplaceListing,
  SkillDetail,
} from '@/lib/kemudi-ai/skills'
import { apiError, detailOf } from './fixtures'
import { MarketplaceTab } from './marketplace'
import { MarketplaceOrigin } from './marketplace-update'

const SHA = '2c5958ecac7cee2b583967a2c4981d0f4a75c579'

const anthropic: Marketplace = {
  id: 1,
  name: 'anthropic-agent-skills',
  repo: 'anthropics/skills',
  ref: '',
  builtin: true,
  url: 'https://github.com/anthropics/skills',
  last_sha: SHA,
  last_fetched_at: '2026-11-14T10:00:00Z',
  error: '',
  description: 'Anthropic example skills',
  plugin_count: 2,
  skill_count: 3,
  created_by: 'builtin',
  created_at: '2026-11-14T09:00:00Z',
}

const custom: Marketplace = {
  ...anthropic,
  id: 2,
  name: 'acme/skills',
  repo: 'acme/skills',
  builtin: false,
  last_sha: '',
  last_fetched_at: '2026-11-14T10:00:00Z',
  error: "GitHub's API rate limit was reached",
  plugin_count: 0,
  skill_count: 0,
}

const skill = {
  description: 'Use when writing.',
  license: 'Apache-2.0',
  version: '',
  valid: true,
  problems: [],
  scan_level: '' as const,
  files: 3,
  size: 1000,
  installed: null,
}

const listing: MarketplaceListing = {
  marketplace: anthropic,
  refreshed: true,
  owner: 'Anthropic',
  kind: 'marketplace',
  plugins: [
    {
      name: 'example-skills',
      description: 'Example skills',
      version: '1.0.0',
      category: 'writing',
      source: { type: 'relative', path: '' },
      supported: true,
      reason: '',
      skills: [
        { ...skill, name: 'doc-coauthoring', path: 'skills/doc-coauthoring' },
        {
          ...skill,
          name: 'internal-comms',
          path: 'skills/internal-comms',
          installed: {
            slug: 'internal-comms',
            source: 'marketplace',
            version: 1,
            enabled: false,
            same_origin: true,
            sha: SHA,
          },
        },
        {
          ...skill,
          name: 'impeccable',
          path: 'skills/impeccable',
          installed: {
            slug: 'impeccable',
            source: 'builtin',
            version: 1,
            enabled: true,
            same_origin: false,
            sha: '',
          },
        },
        {
          ...skill,
          name: 'broken',
          path: 'skills/broken',
          valid: false,
          license: '',
          problems: [
            "frontmatter name 'x' must equal the folder name 'broken'",
          ],
        },
      ],
    },
    {
      name: 'by-url',
      description: '',
      version: '',
      category: '',
      source: { type: 'url', url: 'https://gitlab.com/x/y.git' },
      supported: false,
      reason:
        'git URL sources are not supported yet (GitHub repositories only)',
      skills: [],
    },
  ],
}

const state = vi.hoisted(() => ({
  markets: [] as Marketplace[],
  listing: null as MarketplaceListing | null,
  install: vi.fn(),
  add: vi.fn(),
  refresh: vi.fn(),
  del: vi.fn(),
  check: vi.fn(),
  decide: vi.fn(),
  pluginsFor: [] as (number | null)[],
}))

vi.mock('@/lib/kemudi-ai/skills', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/skills')>()),
  useMarketplaces: () => ({
    data: state.markets,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useMarketplacePlugins: (id: number | null) => {
    state.pluginsFor.push(id)
    return {
      data: state.listing,
      isPending: false,
      isError: false,
      refetch: vi.fn(),
    }
  },
  useInstallSkill: () => ({ mutate: state.install, isPending: false }),
  useAddMarketplace: () => ({ mutate: state.add, isPending: false }),
  useRefreshMarketplace: () => ({ mutate: state.refresh, isPending: false }),
  useDeleteMarketplace: () => ({ mutate: state.del, isPending: false }),
  useCheckUpdate: () => ({ mutate: state.check, isPending: false }),
  useDecideVersion: () => ({ mutate: state.decide, isPending: false }),
}))

beforeEach(() => {
  state.markets = [anthropic, custom]
  state.listing = listing
  state.pluginsFor = []
  for (const f of [
    state.install,
    state.add,
    state.refresh,
    state.del,
    state.check,
    state.decide,
  ])
    f.mockReset()
})

describe('MarketplaceTab', () => {
  it('lists marketplaces with builtin badge, counts, errors', async () => {
    const screen = await render(
      <MarketplaceTab
        selected={null}
        onSelect={vi.fn()}
        onOpenSkill={vi.fn()}
      />
    )
    const list = screen.getByRole('list', { name: 'Marketplaces' })
    await expect.element(list.getByText('anthropic-agent-skills')).toBeVisible()
    await expect.element(list.getByText('Built in')).toBeVisible()
    await expect.element(list.getByText('3 skills in 2 plugins')).toBeVisible()
    await expect.element(list.getByText('2c5958e')).toBeVisible()
    await expect.element(list.getByText('Not fetched yet')).toBeVisible()
    await expect
      .element(list.getByText("GitHub's API rate limit was reached"))
      .toBeVisible()
    // built-ins can't be removed; added ones can
    expect(
      screen
        .getByRole('button', { name: 'Remove anthropic-agent-skills' })
        .query()
    ).toBeNull()
    await expect
      .element(screen.getByRole('button', { name: 'Remove acme/skills' }))
      .toBeVisible()
    // the first marketplace is shown when none is picked
    expect(state.pluginsFor[state.pluginsFor.length - 1]).toBe(1)
  })

  it('shows plugins and skills with install states', async () => {
    const onOpen = vi.fn()
    const screen = await render(
      <MarketplaceTab selected={1} onSelect={vi.fn()} onOpenSkill={onOpen} />
    )
    await expect
      .element(screen.getByRole('heading', { name: /^example-skills/ }))
      .toBeVisible()
    await screen
      .getByRole('button', { name: 'Install doc-coauthoring' })
      .click()
    expect(state.install.mock.calls[0][0]).toEqual({
      id: 1,
      plugin: 'example-skills',
      skill: 'doc-coauthoring',
    })
    await screen.getByRole('button', { name: 'Installed v1' }).click()
    expect(onOpen).toHaveBeenCalledWith('internal-comms')
    await expect
      .element(screen.getByText('Name taken by a Built in skill'))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Install broken' }))
      .toBeDisabled()
    await expect
      .element(screen.getByText(/Can't be installed: frontmatter name/))
      .toBeVisible()
    await expect
      .element(screen.getByText(/Not supported: git URL sources/))
      .toBeVisible()
    await expect
      .element(screen.getByText('anthropics/skills@2c5958e'))
      .toHaveAttribute(
        'href',
        `https://github.com/anthropics/skills/tree/${SHA}`
      )
  })

  it('adds a marketplace, then fetches it', async () => {
    const onSelect = vi.fn()
    const screen = await render(
      <MarketplaceTab selected={1} onSelect={onSelect} onOpenSkill={vi.fn()} />
    )
    await screen.getByLabelText('Add a marketplace').fill('acme/more')
    await screen.getByRole('button', { name: 'Add', exact: true }).click()
    expect(state.add.mock.calls[0][0]).toBe('acme/more')
    state.add.mock.calls[0][1].onSuccess({
      ...custom,
      id: 7,
      repo: 'acme/more',
    })
    expect(onSelect).toHaveBeenCalledWith(7)
    expect(state.refresh.mock.calls[0][0]).toBe(7)
  })

  it('shows a refused repository under the field', async () => {
    const screen = await render(
      <MarketplaceTab selected={1} onSelect={vi.fn()} onOpenSkill={vi.fn()} />
    )
    await screen
      .getByLabelText('Add a marketplace')
      .fill('https://gitlab.com/a/b')
    await screen.getByRole('button', { name: 'Add', exact: true }).click()
    state.add.mock.calls[0][1].onError(
      apiError(422, {
        message: 'only GitHub repositories are supported',
        problems: [],
      })
    )
    await expect
      .element(screen.getByRole('alert'))
      .toHaveTextContent('only GitHub repositories are supported')
  })

  it('asks to refresh a marketplace that was never fetched', async () => {
    state.listing = { ...listing, refreshed: false, plugins: [] }
    const screen = await render(
      <MarketplaceTab selected={2} onSelect={vi.fn()} onOpenSkill={vi.fn()} />
    )
    await expect
      .element(screen.getByText(/Refresh the marketplace to list/))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Refresh acme/skills' }).click()
    expect(state.refresh.mock.calls[0][0]).toBe(2)
  })
})

const PENDING_SHA = 'b'.repeat(64)

function marketplaceSkill(over: Partial<SkillDetail> = {}): SkillDetail {
  const base = detailOf({
    slug: 'internal-comms',
    title: 'internal-comms',
    description: 'Use when writing internal comms.',
    source: 'marketplace',
    license: 'Apache-2.0',
    enabled: true,
    version: 1,
    scan_level: '',
    used_by: [],
    pending_versions: 1,
    updated_at: '2026-11-14T10:00:00Z',
  })
  return {
    ...base,
    origin: {
      marketplace: 'anthropic-agent-skills',
      repo: 'anthropics/skills',
      sha: SHA,
      plugin: 'example-skills',
      path: 'skills/internal-comms',
    },
    origin_url: `https://github.com/anthropics/skills/tree/${SHA}/skills/internal-comms`,
    pending: [
      {
        version: 2,
        sha256: PENDING_SHA,
        origin: { repo: 'anthropics/skills', sha: 'f'.repeat(40) },
        diff: {
          added: ['reference/new.md'],
          removed: [],
          changed: ['SKILL.md'],
        },
        findings: [
          {
            rule: 'git_push',
            severity: 'high',
            path: 'SKILL.md',
            line: 3,
            excerpt: 'git push',
          },
        ],
        warnings: [],
        scan_level: 'high',
        previous_scan_level: '',
        created_by: 'pm (1)',
        created_at: '2026-11-14T10:00:00Z',
      },
    ],
    ...over,
  }
}

describe('MarketplaceOrigin', () => {
  it('links the pinned commit and shows the pending version', async () => {
    const screen = await render(
      <MarketplaceOrigin skill={marketplaceSkill()} />
    )
    await expect
      .element(screen.getByRole('link', { name: /anthropics\/skills@2c5958e/ }))
      .toHaveAttribute(
        'href',
        `https://github.com/anthropics/skills/tree/${SHA}/skills/internal-comms`
      )
    await expect
      .element(
        screen.getByText('Plugin example-skills from anthropic-agent-skills', {
          exact: false,
        })
      )
      .toBeVisible()
    const card = screen.getByRole('article', {
      name: 'Version 2 awaiting approval',
    })
    await expect.element(card.getByText('2 files changed')).toBeVisible()
    await expect.element(card.getByText('reference/new.md')).toBeVisible()
    await expect.element(card.getByText('Runs git push')).toBeVisible()
    await expect.element(card.getByText('Scan: high')).toBeVisible()
  })

  it('checks for an update and shows the result', async () => {
    const screen = await render(
      <MarketplaceOrigin skill={marketplaceSkill({ pending: [] })} />
    )
    await screen.getByRole('button', { name: 'Check for update' }).click()
    expect(state.check.mock.calls[0][0]).toBe('internal-comms')
    state.check.mock.calls[0][1].onSuccess({
      result: { status: 'up_to_date', sha: SHA },
      skill: marketplaceSkill({ pending: [] }),
    })
    await expect
      .element(screen.getByRole('status'))
      .toHaveTextContent('Up to date with 2c5958e.')
  })

  it('approves, asking first when the scan gets worse; rejects', async () => {
    const screen = await render(
      <MarketplaceOrigin skill={marketplaceSkill()} />
    )
    await screen.getByRole('button', { name: 'Approve' }).click()
    expect(state.decide.mock.calls[0][0]).toEqual({
      slug: 'internal-comms',
      version: 2,
      decision: 'approve',
      sha256: PENDING_SHA,
      acceptFindings: false,
    })
    state.decide.mock.calls[0][1].onError(
      apiError(409, {
        message: 'worse',
        problems: [],
        code: 'findings_rise',
        worst: 'high',
        previous: '',
        used_by: [{ project: 'demo', role: 'FE', role_id: 1 }],
      })
    )
    await expect
      .element(screen.getByText(/This version's scan is Scan: high/))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Approve anyway' }).click()
    expect(state.decide.mock.calls[1][0]).toMatchObject({
      decision: 'approve',
      acceptFindings: true,
    })
    state.decide.mock.calls[1][1].onSuccess(marketplaceSkill())
    await screen.getByRole('button', { name: 'Reject' }).click()
    expect(
      state.decide.mock.calls[state.decide.mock.calls.length - 1][0]
    ).toMatchObject({
      decision: 'reject',
      version: 2,
      sha256: PENDING_SHA,
    })
  })
})
