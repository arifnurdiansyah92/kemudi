import { describe, expect, it } from 'vitest'
import { render } from 'vitest-browser-react'
import { PublicKey } from './public-key'

const PUBLIC = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample kemudi-demo-web'
const PRIVATE = [
  '-----BEGIN OPENSSH PRIVATE KEY-----',
  'b3BlbnNzaC1rZXktdjEAAAAA',
  '-----END OPENSSH PRIVATE KEY-----',
].join('\n')

describe('PublicKey', () => {
  it('shows the public key, fingerprint and a copy button', async () => {
    const screen = await render(
      <PublicKey
        id='k'
        value={{ public_key: PUBLIC, fingerprint: 'SHA256:abc123' }}
      />
    )
    await expect
      .element(screen.getByRole('textbox', { name: 'Public key' }))
      .toHaveValue(PUBLIC)
    await expect.element(screen.getByText('SHA256:abc123')).toBeVisible()
    await expect
      .element(screen.getByRole('button', { name: 'Copy' }))
      .toBeVisible()
  })

  it('never renders a private key it is handed', async () => {
    const leaky = {
      public_key: PUBLIC,
      fingerprint: 'SHA256:abc123',
      private_key: PRIVATE,
    }
    const screen = await render(<PublicKey id='k' value={leaky} />)
    await expect
      .element(screen.getByRole('textbox', { name: 'Public key' }))
      .toBeVisible()
    const html = screen.container.innerHTML
    expect(html).not.toContain('PRIVATE KEY')
    expect(html).not.toContain('b3BlbnNzaC1rZXktdjEAAAAA')
  })
})
