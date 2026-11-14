/**
 * A small Markdown renderer for skill files, which are untrusted. It builds
 * React elements and never sets HTML: raw HTML in the source shows as text,
 * and a link becomes clickable only for http(s) and mailto URLs (anything
 * else, `javascript:` included, renders as plain text).
 *
 * Covers what SKILL.md files use: frontmatter, ATX headings, paragraphs,
 * lists, block quotes, fenced code, tables, rules, and inline code,
 * emphasis and links.
 */
import { Fragment, type ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { parseBlocks, safeHref, splitFrontmatter } from './markdown-parse'

const INLINE =
  /(`+)([\s\S]*?[^`])\1(?!`)|\[([^\]]*)\]\(\s*<?((?:[^()\s>]|\([^()\s]*\))*)>?(?:\s+"[^"]*")?\s*\)|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*\s][^*]*)\*|_([^_\s][^_]*)_/g

function renderInline(text: string, key = 'i'): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(INLINE)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const k = `${key}-${n++}`
    if (m[1]) {
      out.push(
        <code
          key={k}
          className='rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]'
        >
          {m[2].trim()}
        </code>
      )
    } else if (m[3] !== undefined) {
      const href = safeHref(m[4])
      out.push(
        href ? (
          <a
            key={k}
            href={href}
            target='_blank'
            rel='noopener noreferrer nofollow'
            className='text-primary underline underline-offset-4'
          >
            {renderInline(m[3], k)}
          </a>
        ) : (
          <span key={k}>{renderInline(m[3], k)}</span>
        )
      )
    } else if (m[5] ?? m[6]) {
      out.push(<strong key={k}>{renderInline(m[5] ?? m[6], k)}</strong>)
    } else {
      out.push(<em key={k}>{renderInline(m[7] ?? m[8], k)}</em>)
    }
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const headingClass: Record<number, string> = {
  1: 'text-lg font-semibold',
  2: 'text-base font-semibold',
  3: 'text-sm font-semibold',
  4: 'text-sm font-semibold',
  5: 'text-sm font-medium',
  6: 'text-sm font-medium text-muted-foreground',
}

export function Markdown({
  source,
  className,
}: {
  source: string
  className?: string
}) {
  const { meta, body } = splitFrontmatter(source)
  const blocks = parseBlocks(body)
  return (
    <div
      className={cn(
        'grid min-w-0 gap-3 text-sm leading-relaxed break-words',
        className
      )}
    >
      {meta.length > 0 && (
        <dl className='grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 rounded-lg border bg-muted/40 px-3 py-2 text-xs'>
          {meta.map(([k, v]) => (
            <Fragment key={k}>
              <dt className='font-mono text-muted-foreground'>{k}</dt>
              <dd className='min-w-0'>{v}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      {blocks.map((b, i) => {
        const key = `b${i}`
        switch (b.kind) {
          case 'heading': {
            const Tag = `h${Math.min(b.level + 1, 6)}` as 'h2'
            return (
              <Tag
                key={key}
                className={cn(headingClass[b.level], i > 0 && 'mt-2')}
              >
                {renderInline(b.text, key)}
              </Tag>
            )
          }
          case 'paragraph':
            return <p key={key}>{renderInline(b.text, key)}</p>
          case 'code':
            return (
              <pre
                key={key}
                className='overflow-x-auto rounded-lg border bg-muted/40 px-3 py-2 font-mono text-xs leading-normal'
              >
                <code>{b.text}</code>
              </pre>
            )
          case 'quote':
            return (
              <blockquote
                key={key}
                className='border-s pl-3 text-muted-foreground'
              >
                {renderInline(b.lines.join(' '), key)}
              </blockquote>
            )
          case 'list': {
            const items = b.items.map((item, j) => (
              <li key={j}>{renderInline(item, `${key}-${j}`)}</li>
            ))
            return b.ordered ? (
              <ol key={key} className='grid list-decimal gap-1 ps-5'>
                {items}
              </ol>
            ) : (
              <ul key={key} className='grid list-disc gap-1 ps-5'>
                {items}
              </ul>
            )
          }
          case 'table':
            return (
              <div key={key} className='overflow-x-auto rounded-lg border'>
                <table className='w-full text-xs'>
                  <thead className='bg-muted/40 text-start'>
                    <tr>
                      {b.head.map((h, j) => (
                        <th
                          key={j}
                          className='px-3 py-1.5 text-start font-medium'
                        >
                          {renderInline(h, `${key}-h${j}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className='divide-y border-t'>
                    {b.rows.map((row, r) => (
                      <tr key={r}>
                        {row.map((c, j) => (
                          <td key={j} className='px-3 py-1.5 align-top'>
                            {renderInline(c, `${key}-${r}-${j}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          case 'rule':
            return <hr key={key} />
        }
      })}
    </div>
  )
}
