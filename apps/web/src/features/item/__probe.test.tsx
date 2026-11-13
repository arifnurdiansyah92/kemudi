import { describe, expect, it } from 'vitest'
import { render } from 'vitest-browser-react'

const U =
  'http://localhost:9100/media/attachments/e/f/4/8/24f9891159f5fad743ad1bda75022bbd4053dda1873eadf373c985f4222d/qa-modal-preview-1794596382867.png#refresh=userstory:12'

describe('probe', () => {
  it('keeps absolute urls with fragments in src', async () => {
    await render(<img alt='p' src={U} />)
    const el = document.querySelector('img')!
    console.log('ATTR', JSON.stringify(el.getAttribute('src')))
    expect(el.getAttribute('src')).toBe(U)
  })
})
