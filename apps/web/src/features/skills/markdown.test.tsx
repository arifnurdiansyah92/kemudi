import { describe, expect, it } from 'vitest'
import { render } from 'vitest-browser-react'
import { Markdown } from './markdown'
import { parseBlocks, safeHref } from './markdown-parse'

describe('safeHref', () => {
  it('keeps http(s) and mailto only', () => {
    expect(safeHref('https://example.com/a')).toBe('https://example.com/a')
    expect(safeHref('mailto:a@example.com')).toBe('mailto:a@example.com')
    for (const bad of [
      'javascript:alert(1)',
      'JaVaScRiPt:alert(1)',
      ' java\tscript:alert(1)',
      'data:text/html,<b>x</b>',
      'vbscript:x',
      'reference/more.md',
      '//evil.example',
    ])
      expect(safeHref(bad), bad).toBeNull()
  })
})

describe('Markdown', () => {
  it('shows raw HTML as text and never makes elements from it', async () => {
    const screen = await render(
      <Markdown
        source={
          '# Title\n\n<script>window.pwned = 1</script>\n\n<img src=x onerror="window.pwned=1">\n'
        }
      />
    )
    await expect
      .element(screen.getByRole('heading', { name: 'Title' }))
      .toBeVisible()
    await expect
      .element(screen.getByText('<script>window.pwned = 1</script>'))
      .toBeVisible()
    expect(screen.container.querySelector('script')).toBeNull()
    expect(screen.container.querySelector('img')).toBeNull()
    expect((window as { pwned?: number }).pwned).toBeUndefined()
  })

  it('strips javascript: links and keeps safe ones', async () => {
    const screen = await render(
      <Markdown
        source={
          'See [docs](https://example.com/docs) and [click](javascript:alert(1)) and [file](reference/x.md).'
        }
      />
    )
    const links = screen.container.querySelectorAll('a')
    expect(links).toHaveLength(1)
    expect(links[0].getAttribute('href')).toBe('https://example.com/docs')
    expect(links[0].getAttribute('rel')).toContain('noopener')
    await expect.element(screen.getByText('click')).toBeVisible()
    // The whole link syntax is consumed, nested parens included.
    expect(screen.container.textContent).toBe('See docs and click and file.')
  })

  it('renders frontmatter, lists, code, tables and emphasis', async () => {
    const screen = await render(
      <Markdown
        source={
          '---\nname: demo\ndescription: Use when testing.\n---\n\n## Steps\n\n- **one**\n- `two`\n\n```sh\necho hi\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n'
        }
      />
    )
    await expect.element(screen.getByText('Use when testing.')).toBeVisible()
    await expect.element(screen.getByRole('listitem').first()).toBeVisible()
    expect(screen.container.querySelector('strong')?.textContent).toBe('one')
    expect(screen.container.querySelector('pre')?.textContent).toBe('echo hi')
    expect(screen.container.querySelectorAll('td')).toHaveLength(2)
  })

  it('parses blocks', () => {
    expect(
      parseBlocks('1. a\n2. b\n\n> q\n\n---\n').map((b) => b.kind)
    ).toEqual(['list', 'quote', 'rule'])
  })
})
