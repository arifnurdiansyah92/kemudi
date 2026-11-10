import { describe, expect, it } from 'vitest'
import { resources } from './resources'

function keys(obj: unknown, prefix = ''): string[] {
  if (typeof obj !== 'object' || obj === null) return [prefix]
  return Object.entries(obj).flatMap(([k, v]) =>
    keys(v, prefix ? `${prefix}.${k}` : k)
  )
}

/** Plural suffixes differ by language: Indonesian has only `_other`. */
const base = (k: string) => k.replace(/_(zero|one|two|few|many|other)$/, '')

describe('locales', () => {
  for (const ns of Object.keys(resources.en) as (keyof typeof resources.en)[]) {
    it(`id/${ns} has every key en/${ns} has, and no others`, () => {
      const en = new Set(keys(resources.en[ns]).map(base))
      const id = new Set(keys(resources.id[ns]).map(base))
      expect([...en].filter((k) => !id.has(k))).toEqual([])
      expect([...id].filter((k) => !en.has(k))).toEqual([])
    })

    it(`id/${ns} has no empty strings`, () => {
      const empty: string[] = []
      const walk = (o: unknown, p: string) => {
        if (typeof o === 'string') {
          if (!o.trim()) empty.push(p)
        } else if (o && typeof o === 'object')
          for (const [k, v] of Object.entries(o)) walk(v, `${p}.${k}`)
      }
      walk(resources.id[ns], ns)
      expect(empty).toEqual([])
    })
  }
})
