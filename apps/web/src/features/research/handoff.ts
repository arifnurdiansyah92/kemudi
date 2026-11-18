import type { ProductSuggestion } from '@/lib/kemudi-ai/product'

/** The requirements text Intake drafts stories from: one numbered entry per
 * suggestion with its problem and proposal. */
export function suggestionsToRequirements(
  suggestions: ProductSuggestion[],
  labels: { problem: string; proposal: string }
) {
  return suggestions
    .map((s, i) =>
      [
        `${i + 1}. ${s.title.trim()}`,
        s.problem.trim() && `${labels.problem}: ${s.problem.trim()}`,
        s.proposal.trim() && `${labels.proposal}: ${s.proposal.trim()}`,
      ]
        .filter(Boolean)
        .join('\n')
    )
    .join('\n\n')
}

/** "Riset kompetitor: Kemudi vs Jira" becomes `riset-kompetitor-kemudi-vs-jira.md`. */
export function reportFileName(title: string, id: number) {
  const name = title
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/, '')
  return `${name || `research-${id}`}.md`
}

export function downloadText(name: string, text: string) {
  const url = URL.createObjectURL(
    new Blob([text], { type: 'text/markdown;charset=utf-8' })
  )
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.append(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
