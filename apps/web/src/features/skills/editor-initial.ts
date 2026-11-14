import type { SkillDetail } from '@/lib/kemudi-ai/skills'
import { splitFrontmatter } from './markdown-parse'

export type EditorInitial = {
  slug: string
  description: string
  license: string
  body: string
  files: { path: string; text: string }[]
}

/** The editor's starting point for a new version: the current version's
 * fields and text files (binary files stay on the server). */
export function initialFrom(
  skill: SkillDetail,
  texts: Record<string, string>
): EditorInitial {
  const { meta, body } = splitFrontmatter(skill.current?.skill_md ?? '')
  const get = (k: string) => {
    const v = meta.find(([key]) => key === k)?.[1] ?? ''
    // A folded or literal YAML block: drop the indicator.
    return v.replace(/^[>|][+-]?\s*/, '')
  }
  return {
    slug: skill.slug,
    description: get('description') || skill.description,
    license: get('license') || skill.license,
    body: body.replace(/^\n+/, ''),
    files: (skill.current?.files ?? [])
      .filter((f) => !f.binary && f.path !== 'SKILL.md')
      .map((f) => ({ path: f.path, text: texts[f.path] ?? '' })),
  }
}
