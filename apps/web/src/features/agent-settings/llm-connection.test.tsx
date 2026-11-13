import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { LlmLevel, LlmTest } from '@/lib/kemudi-ai/agent'
import { LlmSourceBadge, ProjectLlm, RoleLlm } from './llm-connection'

const SECRET = 'sk-live-0123456789abcdef'

const empty: LlmLevel = {
  set: false,
  base_url: '',
  model: '',
  key_set: false,
  key_last4: null,
  effective: {
    llm_source: 'server',
    llm_model: 'deepseek-flash',
    llm_host: 'ai.sumopod.com',
  },
  server_default: { model: 'deepseek-flash', host: 'ai.sumopod.com' },
  updated_by: null,
  updated_at: null,
}

const saved: LlmLevel = {
  ...empty,
  set: true,
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-4o-mini',
  key_set: true,
  key_last4: 'cdef',
  effective: {
    llm_source: 'project',
    llm_model: 'gpt-4o-mini',
    llm_host: 'api.openai.com',
  },
  updated_by: 'webdev',
  updated_at: '2026-11-14T01:00:00Z',
}

const handlers = () => ({
  onSave: vi.fn(() => Promise.resolve()),
  onClear: vi.fn(() => Promise.resolve()),
  onTest: vi.fn(
    (): Promise<LlmTest> =>
      Promise.resolve({
        ok: true,
        latency_ms: 412,
        status: 200,
        error: null,
        llm_source: 'project',
        llm_model: 'gpt-4o-mini',
        llm_host: 'api.openai.com',
      })
  ),
})

describe('ProjectLlm', () => {
  it('drops the typed key after save and never renders it again', async () => {
    const h = handlers()
    const screen = await render(<ProjectLlm level={empty} canEdit {...h} />)
    await screen
      .getByRole('textbox', { name: 'Base URL' })
      .fill('https://api.openai.com/v1')
    await screen.getByRole('textbox', { name: 'Model' }).fill('gpt-4o-mini')
    const key = screen.getByLabelText('API key')
    await key.fill(SECRET)
    await screen.getByRole('button', { name: 'Save' }).click()

    expect(h.onSave).toHaveBeenCalledWith({
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
      api_key: SECRET,
    })
    await expect.element(key).toHaveValue('')

    // The server answers with key_set + last4; the page remounts the form.
    await screen.rerender(
      <ProjectLlm key='after' level={saved} canEdit {...h} />
    )
    await expect.element(screen.getByText('•••• cdef')).toBeVisible()
    expect(document.body.innerHTML).not.toContain(SECRET)
    const values = [...document.querySelectorAll('input')].map((i) => i.value)
    expect(values).not.toContain(SECRET)
  })

  it('does not send an empty key field as a new key', async () => {
    const h = handlers()
    const screen = await render(<ProjectLlm level={saved} canEdit {...h} />)
    await screen.getByRole('textbox', { name: 'Model' }).fill('gpt-4.1-mini')
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(h.onSave).toHaveBeenCalledTimes(1)
    const body = h.onSave.mock.calls[0] as unknown[]
    expect(body[0]).toEqual({
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4.1-mini',
    })
    expect(body[0]).not.toHaveProperty('api_key')
  })

  it('shows the test result with its latency', async () => {
    const h = handlers()
    const screen = await render(<ProjectLlm level={saved} canEdit {...h} />)
    await screen.getByRole('button', { name: 'Test connection' }).click()
    expect(h.onTest).toHaveBeenCalledWith({
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
    })
    await expect.element(screen.getByText('Connected in 412 ms')).toBeVisible()
  })

  it('shows the hierarchy with the server default', async () => {
    const screen = await render(
      <ProjectLlm level={empty} canEdit {...handlers()} />
    )
    await expect
      .element(
        screen.getByText(
          /then the Kemudi server default \(deepseek-flash, ai\.sumopod\.com\)/
        )
      )
      .toBeVisible()
  })

  it('disables every control for members', async () => {
    const screen = await render(
      <ProjectLlm level={saved} canEdit={false} {...handlers()} />
    )
    await expect
      .element(screen.getByRole('textbox', { name: 'Base URL' }))
      .toBeDisabled()
    await expect
      .element(screen.getByRole('button', { name: 'Replace' }))
      .toBeDisabled()
    await expect
      .element(screen.getByRole('button', { name: 'Test connection' }))
      .toBeDisabled()
    await expect
      .element(screen.getByRole('button', { name: 'Clear' }))
      .toBeDisabled()
  })
})

describe('RoleLlm', () => {
  it('sends clear when switched back to the project default', async () => {
    const h = handlers()
    const level = {
      ...saved,
      effective: { ...saved.effective, llm_source: 'agent' as const },
    }
    const screen = await render(
      <RoleLlm roleId={3} level={level} canEdit {...h} />
    )
    const toggle = screen.getByRole('switch', { name: 'Use project default' })
    await expect.element(toggle).not.toBeChecked()
    await toggle.click()
    await screen.getByRole('button', { name: 'Clear connection' }).click()
    expect(h.onClear).toHaveBeenCalledTimes(1)
    await expect.element(toggle).toBeChecked()
  })

  it('shows the fields only when the default is off, and clears nothing unsaved', async () => {
    const h = handlers()
    const screen = await render(
      <RoleLlm roleId={3} level={empty} canEdit {...h} />
    )
    const toggle = screen.getByRole('switch', { name: 'Use project default' })
    await expect.element(toggle).toBeChecked()
    expect(screen.getByLabelText('Base URL').elements()).toHaveLength(0)
    await toggle.click()
    await expect.element(screen.getByLabelText('Base URL')).toBeVisible()
    await toggle.click()
    expect(h.onClear).not.toHaveBeenCalled()
  })
})

describe('LlmSourceBadge', () => {
  it('names each source', async () => {
    const screen = await render(
      <>
        <LlmSourceBadge source='agent' />
        <LlmSourceBadge source='project' />
        <LlmSourceBadge source='server' />
      </>
    )
    await expect.element(screen.getByText('From this agent')).toBeVisible()
    await expect.element(screen.getByText('From project')).toBeVisible()
    await expect
      .element(screen.getByText('Kemudi server default'))
      .toBeVisible()
  })
})
