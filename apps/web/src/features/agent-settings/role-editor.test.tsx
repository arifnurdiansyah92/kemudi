import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import { OVERLAY_MAX, type Role, type RolePrompt } from '@/lib/kemudi-ai/agent'
import { RoleEditor } from './role-editor'

const role: Role = {
  id: 3,
  name: 'Frontend',
  template: 'frontend',
  area: 'web',
  model: 'deepseek-flash',
  repo_ids: [],
  allowed_paths: [],
  denied_paths: [],
  prompt_overlay: 'Use Tailwind.',
  enabled: true,
  version: 2,
  prompt_version: '3.v2.abcdef1234',
  updated_by: 'webdev',
  updated_at: '2026-11-14T00:00:00Z',
  llm_source: 'server',
  llm_model: 'deepseek-flash',
  llm_host: 'ai.sumopod.com',
}

const prompt: RolePrompt = {
  fixed: 'KEMUDI RULES: never push to the default branch.',
  role: 'You are the frontend engineer.',
  scope: { repos: [], allowed_paths: [], denied_paths: [] },
  overlay: 'Use Tailwind.',
  reminder: 'Remember the rules.',
  rendered: '...',
  version: '3.v2.abcdef1234',
}

function renderEditor(onSave = vi.fn()) {
  return render(
    <RoleEditor
      role={role}
      prompt={prompt}
      models={['deepseek-flash', 'qwen-local']}
      repos={[]}
      canEdit
      pending={false}
      onSave={onSave}
    />
  )
}

describe('RoleEditor', () => {
  it('shows the Kemudi rules read-only, not as a text field', async () => {
    const screen = await renderEditor()
    await expect
      .element(screen.getByText('Kemudi rules, not editable'))
      .toBeVisible()
    await expect.element(screen.getByText(prompt.fixed)).toBeVisible()
    const values = screen
      .getByRole('textbox')
      .elements()
      .map((e) => (e as HTMLInputElement).value)
    expect(values).not.toContain(prompt.fixed)
    expect(values).not.toContain(prompt.role)
    await expect
      .element(screen.getByText('Prompt version 3.v2.abcdef1234'))
      .toBeVisible()
  })

  it('saves the overlay', async () => {
    const onSave = vi.fn()
    const screen = await renderEditor(onSave)
    await screen
      .getByRole('textbox', { name: 'Your instructions' })
      .fill('Use Tailwind and shadcn/ui.')
    await screen.getByRole('button', { name: 'Save changes' }).click()
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        prompt_overlay: 'Use Tailwind and shadcn/ui.',
        model: 'deepseek-flash',
        enabled: true,
      })
    )
  })

  it('blocks an overlay over the limit and shows the count', async () => {
    const onSave = vi.fn()
    const screen = await renderEditor(onSave)
    await screen
      .getByRole('textbox', { name: 'Your instructions' })
      .fill('x'.repeat(OVERLAY_MAX + 5))
    await expect
      .element(screen.getByText(/8,005 \/ 8,000 characters/))
      .toBeVisible()
    await expect
      .element(screen.getByText(/5 characters over the limit/))
      .toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Save changes' }))
      .toBeDisabled()
    expect(onSave).not.toHaveBeenCalled()
  })
})
