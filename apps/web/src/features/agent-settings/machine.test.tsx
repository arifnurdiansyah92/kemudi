import { describe, expect, it } from 'vitest'
import { render } from 'vitest-browser-react'
import type { Preflight } from '@/lib/kemudi-ai/agent'
import { PreflightResult } from './machine'

const base: Preflight = {
  ok: true,
  cpu: 8,
  ram_gb: 16,
  disk_gb: 120,
  docker: '27.3.1',
  arch: 'x86_64',
  slots: 2,
  problems: [],
  host_key: 'SHA256:host',
  checked_at: '2026-11-14T03:00:00Z',
  error: null,
  minimum: { cpu: 4, ram_gb: 8, disk_gb: 40 },
  executor: 'ssh',
  remote_execution: false,
}

describe('PreflightResult', () => {
  it('shows each fact against the minimum', async () => {
    const screen = await render(<PreflightResult result={base} />)
    await expect.element(screen.getByText('8 vCPU')).toBeVisible()
    await expect.element(screen.getByText('4 vCPU')).toBeVisible()
    await expect.element(screen.getByText('27.3.1')).toBeVisible()
  })

  it('shows the Docker problem and zero slots when Docker is missing', async () => {
    const screen = await render(
      <PreflightResult
        result={{
          ...base,
          ok: false,
          docker: null,
          slots: 0,
          problems: ['Docker: not installed or not reachable by this user'],
        }}
      />
    )
    await expect.element(screen.getByText('Not found')).toBeVisible()
    await expect
      .element(
        screen.getByText('Docker: not installed or not reachable by this user')
      )
      .toBeVisible()
    const slots = screen.getByRole('row', { name: /Job slots/ })
    await expect.element(slots.getByRole('cell').first()).toHaveTextContent('0')
  })
})
