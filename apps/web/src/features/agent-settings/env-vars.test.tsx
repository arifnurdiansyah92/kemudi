import { AxiosError, type AxiosResponse } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'
import type { EnvVar } from '@/lib/kemudi-ai/agent'
import { EnvVarsCard } from './env-vars'

const state = vi.hoisted(() => ({
  vars: [] as EnvVar[],
  save: vi.fn(),
  remove: vi.fn(),
}))

vi.mock('@/lib/kemudi-ai/agent', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/kemudi-ai/agent')>()),
  useEnvVars: () => ({ isPending: false, isError: false, data: state.vars }),
  useSaveEnvVar: () => ({ mutate: state.save, isPending: false }),
  useDeleteEnvVar: () => ({ mutate: state.remove, isPending: false }),
}))

function row(over: Partial<EnvVar>): EnvVar {
  return {
    name: 'X',
    secret: false,
    set: true,
    value: null,
    required: false,
    description: '',
    in_runbook: false,
    updated_by: 'arif (1)',
    updated_at: '2026-11-14T03:00:00Z',
    ...over,
  }
}

const vars: EnvVar[] = [
  row({ name: 'API_URL', value: 'http://api:5000' }),
  row({
    name: 'JWT_SECRET_KEY',
    secret: true,
    required: true,
    in_runbook: true,
    description: 'any 64-char hex for testing',
  }),
  row({
    name: 'QA_ADMIN_PASSWORD',
    secret: true,
    set: false,
    required: true,
    in_runbook: true,
    updated_by: '',
    updated_at: null,
  }),
]

function wrap(ui: React.ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>
  )
}

/** A value typed in the form; made at run time, not a fixed credential. */
const typed = () => `dev-${Math.random().toString(36).slice(2, 10)}`

beforeEach(() => {
  state.save.mockReset()
  state.remove.mockReset()
  state.vars = vars
})

describe('EnvVarsCard', () => {
  it('says the values are for test and development only', async () => {
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await expect
      .element(screen.getByText(/Never enter production credentials/))
      .toBeVisible()
  })

  it('lists plain values, hides secrets and flags missing required ones', async () => {
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await expect.element(screen.getByText('http://api:5000')).toBeVisible()
    await expect.element(screen.getByText('JWT_SECRET_KEY')).toBeVisible()
    await expect.element(screen.getByText('Hidden')).toBeVisible()
    await expect.element(screen.getByText('Required, not set')).toBeVisible()
    await expect
      .element(screen.getByText('1 required value is missing.'))
      .toBeVisible()
    await expect
      .element(screen.getByText('any 64-char hex for testing'))
      .toBeVisible()
  })

  it('gives members no edit controls', async () => {
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit={false} />))
    await expect.element(screen.getByText('http://api:5000')).toBeVisible()
    expect(screen.getByRole('button').elements()).toHaveLength(0)
  })

  it('adds a secret value', async () => {
    state.vars = []
    const value = typed()
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await expect.element(screen.getByText('No values yet.')).toBeVisible()
    await screen.getByRole('button', { name: 'Add value' }).click()
    await screen.getByRole('textbox', { name: 'Name' }).fill('JWT_SECRET_KEY')
    const input = screen.getByLabelText('Value', { exact: true })
    await expect.element(input).toHaveAttribute('type', 'password')
    await input.fill(value)
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(state.save).toHaveBeenCalledOnce()
    expect(state.save.mock.calls[0][0]).toEqual({
      name: 'JWT_SECRET_KEY',
      value,
      secret: true,
    })
  })

  it('checks the name before sending', async () => {
    state.vars = []
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Add value' }).click()
    await screen.getByRole('textbox', { name: 'Name' }).fill('jwt-key')
    await screen.getByLabelText('Value', { exact: true }).fill(typed())
    await screen.getByRole('button', { name: 'Save' }).click()
    await expect
      .element(screen.getByText(/Use capital letters, digits and _/))
      .toBeVisible()
    expect(state.save).not.toHaveBeenCalled()
  })

  it('keeps a stored secret when the value is left empty', async () => {
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Edit JWT_SECRET_KEY' }).click()
    await expect
      .element(screen.getByText(/A value is stored. Leave this empty/))
      .toBeVisible()
    await expect
      .element(screen.getByLabelText('Value', { exact: true }))
      .toHaveValue('')
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(state.save.mock.calls[0][0]).toEqual({
      name: 'JWT_SECRET_KEY',
      value: null,
      secret: true,
    })
  })

  it('asks for the value again when a secret becomes plain', async () => {
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Edit JWT_SECRET_KEY' }).click()
    await screen.getByRole('switch', { name: 'Secret' }).click()
    await screen.getByRole('button', { name: 'Save' }).click()
    await expect
      .element(screen.getByText(/Enter the value again/))
      .toBeVisible()
    expect(state.save).not.toHaveBeenCalled()
  })

  it('fills a runbook name that has no value yet', async () => {
    const value = typed()
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Set QA_ADMIN_PASSWORD' }).click()
    await expect
      .element(screen.getByRole('textbox', { name: 'Name' }))
      .toHaveValue('QA_ADMIN_PASSWORD')
    await screen.getByLabelText('Value', { exact: true }).fill(value)
    await screen.getByRole('button', { name: 'Save' }).click()
    expect(state.save.mock.calls[0][0]).toEqual({
      name: 'QA_ADMIN_PASSWORD',
      value,
      secret: true,
    })
  })

  it('shows what the server refuses', async () => {
    state.vars = []
    state.save.mockImplementation(
      (_body: unknown, opts: { onError: (e: unknown) => void }) =>
        opts.onError(
          new AxiosError('Unprocessable', 'ERR_BAD_REQUEST', undefined, null, {
            status: 422,
            data: { detail: "env name 'PATH' is reserved" },
          } as AxiosResponse)
        )
    )
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Add value' }).click()
    await screen.getByRole('textbox', { name: 'Name' }).fill('PATH')
    await screen.getByLabelText('Value', { exact: true }).fill(typed())
    await screen.getByRole('button', { name: 'Save' }).click()
    await expect
      .element(screen.getByRole('alert'))
      .toHaveTextContent("env name 'PATH' is reserved")
  })

  it('deletes after confirming', async () => {
    const screen = await render(wrap(<EnvVarsCard slug='pf' canEdit />))
    await screen.getByRole('button', { name: 'Edit API_URL' }).click()
    await screen.getByRole('button', { name: 'Delete' }).click()
    await expect
      .element(screen.getByRole('alertdialog'))
      .toHaveTextContent('Delete API_URL?')
    await screen
      .getByRole('alertdialog')
      .getByRole('button', { name: 'Delete' })
      .click()
    expect(state.remove).toHaveBeenCalledOnce()
    expect(state.remove.mock.calls[0][0]).toBe('API_URL')
  })
})
