import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { DraftCheck, SkillDraft } from '@/lib/kemudi-ai/skills'
import { initialFrom } from './editor-initial'
import { apiError, detailOf, notes } from './fixtures'
import { SkillEditor } from './skill-editor'

const state = vi.hoisted(() => ({
  drafts: [] as (SkillDraft | null)[],
  check: (_d: SkillDraft): DraftCheck | undefined => undefined,
  save: vi.fn(),
}))

vi.mock('@/lib/kemudi-ai/skills', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/skills')>()),
  useCheckDraft: (draft: SkillDraft | null) => {
    state.drafts.push(draft)
    return {
      data: draft ? state.check(draft) : undefined,
      isFetching: false,
      isError: false,
    }
  },
  useSaveSkill: () => ({ mutate: state.save, isPending: false }),
}))

function verdict(d: SkillDraft): DraftCheck {
  const ok = /^[a-z0-9-]+$/.test(d.slug)
  const md = `---\nname: ${d.slug}\ndescription: ${d.description.slice(0, 300)}\n---\n\n${d.body}`
  return {
    ok,
    problems: ok ? [] : [`folder name '${d.slug}': use 1-64 of a-z`],
    warnings: [],
    findings: d.body.includes('git push')
      ? [
          {
            rule: 'git_push',
            severity: 'high',
            path: 'SKILL.md',
            line: 1,
            excerpt: 'git push',
          },
        ]
      : [],
    worst: d.body.includes('git push') ? 'high' : '',
    skill_md: md,
    agent_skill_md: md,
    size: md.length,
  }
}

beforeEach(() => {
  state.drafts = []
  state.check = verdict
  state.save.mockReset()
})

async function fillBasics(
  screen: Awaited<ReturnType<typeof render>>,
  slug: string
) {
  await screen.getByRole('textbox', { name: 'Name' }).fill(slug)
  await screen
    .getByRole('textbox', { name: 'Description' })
    .fill('Use when writing release notes.')
  await screen
    .getByRole('textbox', { name: 'Instructions' })
    .fill('# Notes\n\nKeep them short.')
}

describe('SkillEditor', () => {
  it('checks the draft after a pause and shows problems; save waits for a valid draft', async () => {
    const screen = await render(<SkillEditor onSaved={vi.fn()} />)
    await expect
      .element(
        screen.getByText('Fill in a name and a description to check the skill.')
      )
      .toBeVisible()
    await fillBasics(screen, 'Bad Name')
    await expect
      .element(screen.getByText("folder name 'Bad Name': use 1-64 of a-z"))
      .toBeVisible()
    await expect.element(screen.getByText('1 problem to fix')).toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Save skill' }))
      .toBeDisabled()
    // Debounced: the check never saw a half-typed name.
    const slugs = state.drafts.filter(Boolean).map((d) => d!.slug)
    expect(slugs.every((s) => s === 'Bad Name')).toBe(true)
  })

  it('previews what Awak gets, shows findings and saves', async () => {
    const onSaved = vi.fn()
    state.save.mockImplementation((_vars, opts) =>
      opts.onSuccess({ ...detailOf(notes), slug: 'notes' })
    )
    const screen = await render(<SkillEditor onSaved={onSaved} />)
    await fillBasics(screen, 'notes')
    await screen
      .getByRole('textbox', { name: 'Instructions' })
      .fill('Never git push.')
    await expect.element(screen.getByText('Ready to save')).toBeVisible()
    await expect.element(screen.getByText('Runs git push')).toBeVisible()
    await expect.element(screen.getByText('What Awak gets')).toBeVisible()
    await expect
      .element(screen.getByRole('tabpanel').getByText('Never git push.'))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Add file' }).click()
    await screen
      .getByRole('textbox', { name: 'Contents of reference/note-1.md' })
      .fill('Short sentences.')
    await screen.getByRole('button', { name: 'Save skill' }).click()
    expect(state.save).toHaveBeenCalledWith(
      {
        draft: {
          slug: 'notes',
          description: 'Use when writing release notes.',
          body: 'Never git push.',
          license: '',
          files: { 'reference/note-1.md': 'Short sentences.' },
        },
        existing: false,
      },
      expect.anything()
    )
    expect(onSaved).toHaveBeenCalledWith('notes')
  })

  it('counts description characters and warns past the agent cut', async () => {
    const screen = await render(<SkillEditor onSaved={vi.fn()} />)
    await screen
      .getByRole('textbox', { name: 'Description' })
      .fill('x'.repeat(301))
    await expect.element(screen.getByText('301 / 1024')).toBeVisible()
    await expect
      .element(screen.getByText(/Awak sees only the first 300 characters\./))
      .toBeVisible()
  })

  it('shows the server problems when saving fails', async () => {
    state.save.mockImplementation((_vars, opts) =>
      opts.onError(
        apiError(409, { message: 'a skill named notes exists', problems: [] })
      )
    )
    const screen = await render(<SkillEditor onSaved={vi.fn()} />)
    await fillBasics(screen, 'notes')
    await expect.element(screen.getByText('Ready to save')).toBeVisible()
    await screen.getByRole('button', { name: 'Save skill' }).click()
    await expect
      .element(screen.getByText('a skill named notes exists'))
      .toBeVisible()
  })

  it('starts a new version from the current one, name locked', async () => {
    const skill = detailOf(notes)
    const initial = initialFrom(skill, {
      'reference/style.md': 'Use short sentences.',
    })
    expect(initial).toEqual({
      slug: 'release-notes',
      description: 'Use when writing release notes.',
      license: '',
      body: '# How to\n\nRead [the guide](javascript:alert(1)) first.\n',
      files: [{ path: 'reference/style.md', text: 'Use short sentences.' }],
    })
    const screen = await render(
      <SkillEditor initial={initial} existing={skill} onSaved={vi.fn()} />
    )
    await expect
      .element(screen.getByText('New version of release-notes'))
      .toBeVisible()
    await expect
      .element(
        screen.getByText(/1 binary file from the current version is kept/)
      )
      .toBeVisible()
    await expect
      .element(screen.getByRole('textbox', { name: 'Name' }))
      .toBeDisabled()
    await expect
      .element(screen.getByRole('button', { name: 'Save version' }))
      .toBeVisible()
  })
})
