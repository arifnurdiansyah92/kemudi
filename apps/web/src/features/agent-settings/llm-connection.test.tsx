import type { ComponentProps } from 'react'
import { AxiosError, AxiosHeaders } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { LlmLevel, LlmModelsIn, LlmTest } from '@/lib/kemudi-ai/agent'
import { LlmSourceBadge, ProjectLlm } from './llm-connection'

const SECRET = 'sk-live-0123456789abcdef'

const models = vi.hoisted(() => ({
  calls: [] as { body: LlmModelsIn; enabled: boolean }[],
}))

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useLlmModels: (_slug: string, body: LlmModelsIn, enabled: boolean) => {
    models.calls.push({ body, enabled })
    return {
      data: enabled
        ? {
            ok: true,
            models: ['gpt-4.1-mini', 'gpt-4o', 'gpt-4o-mini'],
            source: 'project',
            host: 'api.openai.com',
            error: null,
          }
        : undefined,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
    }
  },
}))

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

const client = new QueryClient()

function Project(props: Omit<ComponentProps<typeof ProjectLlm>, 'slug'>) {
  return (
    <QueryClientProvider client={client}>
      <ProjectLlm slug='demo' {...props} />
    </QueryClientProvider>
  )
}

describe('ProjectLlm', () => {
  it('drops the typed key after save and never renders it again', async () => {
    const h = handlers()
    const screen = await render(<Project level={empty} canEdit {...h} />)
    await screen
      .getByRole('combobox', { name: 'Provider' })
      .selectOptions('OpenAI')
    await expect
      .element(screen.getByRole('textbox', { name: 'Base URL' }))
      .toHaveValue('https://api.openai.com/v1')
    const key = screen.getByLabelText('API key')
    await key.fill(SECRET)
    await screen.getByRole('combobox', { name: 'Model' }).click()
    await screen.getByRole('option', { name: 'gpt-4o-mini' }).click()
    await screen.getByRole('button', { name: 'Save' }).click()

    expect(h.onSave).toHaveBeenCalledWith({
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
      api_key: SECRET,
    })
    await expect.element(key).toHaveValue('')

    // The server answers with key_set + last4; the page remounts the form.
    await screen.rerender(<Project key='after' level={saved} canEdit {...h} />)
    await expect.element(screen.getByText('•••• cdef')).toBeVisible()
    expect(document.body.innerHTML).not.toContain(SECRET)
    const values = [...document.querySelectorAll('input')].map((i) => i.value)
    expect(values).not.toContain(SECRET)
  })

  it('lists models for the unsaved provider and accepts a typed model', async () => {
    const h = handlers()
    models.calls.length = 0
    const screen = await render(<Project level={saved} canEdit {...h} />)
    // Saved values: the saved connection.
    await screen.getByRole('combobox', { name: 'Model' }).click()
    expect(models.calls[models.calls.length - 1]).toEqual({
      body: {},
      enabled: true,
    })
    await expect
      .element(screen.getByText('From project · api.openai.com · 3 models'))
      .toBeVisible()
    await screen
      .getByPlaceholder('Search or type a model name')
      .fill('my-finetune:v2')
    await screen.getByRole('option', { name: 'Use “my-finetune:v2”' }).click()
    await expect
      .element(screen.getByRole('combobox', { name: 'Model' }))
      .toHaveTextContent('my-finetune:v2')
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(h.onSave.mock.calls[0] as unknown[]).toEqual([
      { base_url: 'https://api.openai.com/v1', model: 'my-finetune:v2' },
    ])
    // Editing the URL makes it Custom and lists that address instead.
    await screen
      .getByRole('textbox', { name: 'Base URL' })
      .fill('https://llm.internal.example/v1')
    await expect
      .element(screen.getByRole('combobox', { name: 'Provider' }))
      .toHaveValue('custom')
    await expect
      .poll(() => models.calls[models.calls.length - 1]?.body)
      .toEqual({ base_url: 'https://llm.internal.example/v1' })
  })

  it('does not send an empty key field as a new key', async () => {
    const h = handlers()
    const screen = await render(<Project level={saved} canEdit {...h} />)
    await screen.getByRole('combobox', { name: 'Model' }).click()
    await screen.getByRole('option', { name: 'gpt-4.1-mini' }).click()
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
    const screen = await render(<Project level={saved} canEdit {...h} />)
    await screen.getByRole('button', { name: 'Test connection' }).click()
    expect(h.onTest).toHaveBeenCalledWith({
      base_url: 'https://api.openai.com/v1',
      model: 'gpt-4o-mini',
    })
    await expect.element(screen.getByText('Connected in 412 ms')).toBeVisible()
  })

  it('shows the hierarchy with the server default', async () => {
    const screen = await render(
      <Project level={empty} canEdit {...handlers()} />
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
      <Project level={saved} canEdit={false} {...handlers()} />
    )
    for (const [role, name] of [
      ['textbox', 'Base URL'],
      ['combobox', 'Provider'],
      ['combobox', 'Model'],
      ['button', 'Refresh models'],
      ['button', 'Replace'],
      ['button', 'Test connection'],
      ['button', 'Clear'],
    ] as const) {
      await expect.element(screen.getByRole(role, { name })).toBeDisabled()
    }
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

describe('ProjectLlm over plain http', () => {
  const PUBLIC_HTTP = 'http://203.0.113.5:8000/v1'
  const ACK = 'I understand, use unencrypted http'

  it('asks for the acknowledgement before saving http to a public address', async () => {
    const h = handlers()
    const screen = await render(<Project level={saved} canEdit {...h} />)
    await screen.getByRole('textbox', { name: 'Base URL' }).fill(PUBLIC_HTTP)
    await expect
      .element(screen.getByText('Unencrypted connection'))
      .toBeVisible()
    const save = screen.getByRole('button', { name: 'Save' })
    await expect.element(save).toBeDisabled()
    await expect
      .element(screen.getByRole('button', { name: 'Test connection' }))
      .toBeDisabled()
    await screen.getByRole('checkbox', { name: ACK }).click()
    await expect.element(save).toBeEnabled()
    await save.click()
    expect(h.onSave).toHaveBeenCalledWith({
      base_url: PUBLIC_HTTP,
      model: 'gpt-4o-mini',
      allow_insecure_http: true,
    })
  })

  it('asks again when the address changes', async () => {
    const screen = await render(
      <Project level={saved} canEdit {...handlers()} />
    )
    const url = screen.getByRole('textbox', { name: 'Base URL' })
    await url.fill(PUBLIC_HTTP)
    await screen.getByRole('checkbox', { name: ACK }).click()
    await url.fill('http://198.51.100.7/v1')
    await expect
      .element(screen.getByRole('checkbox', { name: ACK }))
      .not.toBeChecked()
    await expect
      .element(screen.getByRole('button', { name: 'Save' }))
      .toBeDisabled()
  })

  it('leaves http to a private address alone', async () => {
    const h = handlers()
    const screen = await render(<Project level={saved} canEdit {...h} />)
    for (const url of [
      'http://192.168.1.20:11434/v1',
      'http://host.docker.internal:11434/v1',
      'http://172.20.0.4/v1',
      'http://ollama:11434/v1',
    ]) {
      await screen.getByRole('textbox', { name: 'Base URL' }).fill(url)
      expect(
        screen.getByText('Unencrypted connection').elements()
      ).toHaveLength(0)
    }
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(h.onSave).toHaveBeenCalledWith({
      base_url: 'http://ollama:11434/v1',
      model: 'gpt-4o-mini',
    })
  })

  it('shows the notice when the server refuses a URL the client took as private', async () => {
    const h = handlers()
    h.onSave.mockImplementationOnce(() =>
      Promise.reject(
        new AxiosError('Unprocessable Entity', '422', undefined, undefined, {
          status: 422,
          statusText: 'Unprocessable Entity',
          headers: {},
          config: { headers: new AxiosHeaders() },
          data: {
            detail: [
              {
                loc: ['body'],
                msg: 'Value error, http:// is only allowed to a private or loopback address; use https://, or tick "allow unencrypted http" to send the key and prompts unencrypted',
              },
            ],
          },
        })
      )
    )
    const screen = await render(<Project level={saved} canEdit {...h} />)
    await screen
      .getByRole('textbox', { name: 'Base URL' })
      .fill('http://llm-gateway:8000/v1')
    await screen.getByRole('button', { name: 'Save' }).click()
    await expect
      .element(screen.getByText('Unencrypted connection'))
      .toBeVisible()
    await screen.getByRole('checkbox', { name: ACK }).click()
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(h.onSave).toHaveBeenLastCalledWith({
      base_url: 'http://llm-gateway:8000/v1',
      model: 'gpt-4o-mini',
      allow_insecure_http: true,
    })
  })

  it('marks a saved insecure connection and keeps its acknowledgement', async () => {
    const h = handlers()
    const insecure: LlmLevel = {
      ...saved,
      base_url: PUBLIC_HTTP,
      insecure_http: true,
      effective: {
        ...saved.effective,
        llm_host: '203.0.113.5',
        llm_insecure_http: true,
      },
    }
    const screen = await render(<Project level={insecure} canEdit {...h} />)
    await expect
      .element(screen.getByText('Unencrypted', { exact: true }))
      .toBeVisible()
    await expect
      .element(screen.getByRole('checkbox', { name: ACK }))
      .toBeChecked()
    await screen.getByRole('combobox', { name: 'Model' }).click()
    await screen.getByRole('option', { name: 'gpt-4o', exact: true }).click()
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(h.onSave).toHaveBeenCalledWith({
      base_url: PUBLIC_HTTP,
      model: 'gpt-4o',
      allow_insecure_http: true,
    })
  })
})
