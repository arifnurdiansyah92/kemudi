import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import {
  OVERLAY_MAX,
  type LlmLevel,
  type LlmModelsIn,
  type Role,
  type RolePrompt,
} from '@/lib/kemudi-ai/agent'
import { RoleEditor } from './role-editor'

const calls = vi.hoisted(() => [] as LlmModelsIn[])

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useLlmModels: (_slug: string, body: LlmModelsIn, enabled: boolean) => {
    if (enabled) calls.push(body)
    const own = Boolean(body.base_url)
    return {
      data: enabled
        ? {
            ok: true,
            models: own ? ['llama3.3'] : ['deepseek-flash', 'kimi-k2'],
            source: own ? 'agent' : 'project',
            host: own ? 'api.groq.com' : 'ai.sumopod.com',
            error: null,
          }
        : undefined,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
    }
  },
}))

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

const server = { model: 'deepseek-flash', host: 'ai.sumopod.com' }

const projectLevel: LlmLevel = {
  set: true,
  base_url: 'https://ai.sumopod.com/v1',
  model: 'kimi-k2',
  key_set: true,
  key_last4: 'wxyz',
  effective: {
    llm_source: 'project',
    llm_model: 'kimi-k2',
    llm_host: 'ai.sumopod.com',
  },
  server_default: server,
  updated_by: 'webdev',
  updated_at: '2026-11-14T00:00:00Z',
}

const noLevel: LlmLevel = {
  set: false,
  base_url: '',
  model: '',
  key_set: false,
  key_last4: null,
  effective: projectLevel.effective,
  server_default: server,
  updated_by: null,
  updated_at: null,
}

const client = new QueryClient()

function renderEditor(
  onSave = vi.fn(),
  { r = role, level = noLevel }: { r?: Role | null; level?: LlmLevel } = {}
) {
  return render(
    <QueryClientProvider client={client}>
      <RoleEditor
        slug='demo'
        role={r}
        level={r ? level : null}
        projectLevel={projectLevel}
        prompt={prompt}
        repos={[]}
        canEdit
        pending={false}
        onSave={onSave}
      />
    </QueryClientProvider>
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
      }),
      null
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

  it('lists the project provider models with the default and lets the role override', async () => {
    const onSave = vi.fn()
    const screen = await renderEditor(onSave, { r: { ...role, model: '' } })
    const toggle = screen.getByRole('switch', { name: 'Use project default' })
    await expect.element(toggle).toBeChecked()
    // Provider and key stay hidden; the model picker stays.
    expect(screen.getByLabelText('Base URL').elements()).toHaveLength(0)
    const picker = screen.getByRole('combobox', { name: 'Model' })
    await expect
      .element(picker)
      .toHaveTextContent('Connection default (kimi-k2)')
    await picker.click()
    expect(calls[calls.length - 1]).toEqual({})
    await expect
      .element(screen.getByText('From project · ai.sumopod.com · 2 models'))
      .toBeVisible()
    await screen.getByRole('option', { name: 'deepseek-flash' }).click()
    await screen.getByRole('button', { name: 'Save changes' }).click()
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ model: 'deepseek-flash' }),
      null
    )
  })

  it('saves its own connection with the one model field', async () => {
    const onSave = vi.fn()
    const screen = await renderEditor(onSave)
    await screen.getByRole('switch', { name: 'Use project default' }).click()
    await screen
      .getByRole('combobox', { name: 'Provider' })
      .selectOptions('Groq')
    await screen.getByLabelText('API key').fill('gsk_role0123456789abcd')
    await screen.getByRole('combobox', { name: 'Model' }).click()
    await expect
      .poll(() => calls[calls.length - 1])
      .toEqual({
        role_id: 3,
        base_url: 'https://api.groq.com/openai/v1',
        api_key: 'gsk_role0123456789abcd',
      })
    await screen.getByRole('option', { name: 'llama3.3' }).click()
    await screen.getByRole('button', { name: 'Save changes' }).click()
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ model: 'llama3.3' }),
      {
        base_url: 'https://api.groq.com/openai/v1',
        api_key: 'gsk_role0123456789abcd',
      }
    )
    // One model field only.
    expect(
      screen.getByRole('combobox', { name: 'Model' }).elements()
    ).toHaveLength(1)
  })

  it('clears a saved own connection when switched back to the project default', async () => {
    const onSave = vi.fn()
    const own: LlmLevel = {
      ...projectLevel,
      base_url: 'https://api.groq.com/openai/v1',
      model: 'llama3.3',
      key_last4: 'QRST',
    }
    const screen = await renderEditor(onSave, {
      r: { ...role, model: '' },
      level: own,
    })
    const picker = screen.getByRole('combobox', { name: 'Model' })
    // An older role: its connection's model fills the one field.
    await expect.element(picker).toHaveTextContent('llama3.3')
    await screen.getByRole('switch', { name: 'Use project default' }).click()
    await expect
      .element(screen.getByText(/removes this agent's own connection/))
      .toBeVisible()
    await screen.getByRole('button', { name: 'Save changes' }).click()
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ model: 'llama3.3' }),
      { clear: true }
    )
  })
})
