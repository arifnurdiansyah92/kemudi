/**
 * Parsing for the skill Markdown renderer (markdown.tsx): blocks,
 * frontmatter, and the link allowlist. No HTML is produced here.
 */

/** http(s) or mailto only, after dropping what browsers ignore. */
export function safeHref(raw: string): string | null {
  // eslint-disable-next-line no-control-regex
  const url = raw.replace(/[\u0000-\x20\u007f-\u009f]/g, '')
  return /^(https?:\/\/|mailto:)/i.test(url) ? url : null
}

type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'quote'; lines: string[] }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'table'; head: string[]; rows: string[][] }
  | { kind: 'rule' }

const FENCE = /^\s{0,3}(`{3,}|~{3,})\s*([\w+-]*)/
const HEADING = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/
const BULLET = /^\s*([-*+]|\d{1,9}[.)])\s+(.*)$/
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

function cells(line: string) {
  return line
    .trim()
    .replace(/^\||\|$/g, '')
    .split('|')
    .map((c) => c.trim())
}

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n')
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i++
      continue
    }
    const fence = FENCE.exec(line)
    if (fence) {
      const close = fence[1]
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith(close))
        body.push(lines[i++])
      i++
      blocks.push({ kind: 'code', lang: fence[2], text: body.join('\n') })
      continue
    }
    const heading = HEADING.exec(line)
    if (heading) {
      blocks.push({
        kind: 'heading',
        level: heading[1].length,
        text: heading[2],
      })
      i++
      continue
    }
    if (RULE.test(line)) {
      blocks.push({ kind: 'rule' })
      i++
      continue
    }
    if (/^\s{0,3}>/.test(line)) {
      const quote: string[] = []
      while (i < lines.length && /^\s{0,3}>/.test(lines[i]))
        quote.push(lines[i++].replace(/^\s{0,3}>\s?/, ''))
      blocks.push({ kind: 'quote', lines: quote })
      continue
    }
    if (line.includes('|') && TABLE_SEP.test(lines[i + 1] ?? '')) {
      const head = cells(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim())
        rows.push(cells(lines[i++]))
      blocks.push({ kind: 'table', head, rows })
      continue
    }
    const bullet = BULLET.exec(line)
    if (bullet) {
      const ordered = /\d/.test(bullet[1])
      const items: string[] = []
      while (i < lines.length) {
        const m = BULLET.exec(lines[i])
        if (m && /\d/.test(m[1]) === ordered) {
          items.push(m[2])
          i++
        } else if (
          lines[i].trim() &&
          /^\s{2,}/.test(lines[i]) &&
          items.length
        ) {
          // A continuation line (or a nested item, shown flat).
          items[items.length - 1] += ' ' + lines[i].trim().replace(BULLET, '$2')
          i++
        } else break
      }
      blocks.push({ kind: 'list', ordered, items })
      continue
    }
    const para: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() &&
      !FENCE.test(lines[i]) &&
      !HEADING.test(lines[i]) &&
      !BULLET.test(lines[i]) &&
      !/^\s{0,3}>/.test(lines[i])
    )
      para.push(lines[i++].trim())
    blocks.push({ kind: 'paragraph', text: para.join(' ') })
  }
  return blocks
}

const FRONT = /^---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)/

/** Frontmatter as key/value lines (top-level keys only) and the body. */
export function splitFrontmatter(source: string) {
  const text = source.replace(/\r\n?/g, '\n')
  const m = FRONT.exec(text)
  if (!m) return { meta: [] as [string, string][], body: text }
  const meta: [string, string][] = []
  for (const line of m[1].split('\n')) {
    const kv = /^([A-Za-z][\w-]*):\s*(.*)$/.exec(line)
    if (kv) meta.push([kv[1], kv[2].replace(/^(['"])(.*)\1$/, '$2')])
    else if (meta.length && /^\s+\S/.test(line))
      meta[meta.length - 1][1] += ' ' + line.trim()
  }
  return { meta, body: text.slice(m[0].length) }
}
