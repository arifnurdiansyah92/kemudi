/** Filter state and matching, shared by every filtered list. */

export type FacetValue = string | number
export type FacetOption = {
  value: FacetValue
  label: string
  color?: string | null
}

/** A way to narrow a list: its choices, and the values an item has. */
export type Facet<T> = {
  key: string
  label: string
  options: FacetOption[]
  values: (item: T) => FacetValue[]
}

export type FilterState = { q: string; facets: Record<string, FacetValue[]> }
export const emptyFilters: FilterState = { q: '', facets: {} }

export function isFiltering(f: FilterState) {
  return !!f.q.trim() || Object.values(f.facets).some((v) => v.length > 0)
}

/** Items matching the search (subject or #ref) and every active facet. */
export function applyFilters<T extends { ref: number; subject: string }>(
  items: T[],
  facets: Facet<T>[],
  f: FilterState
) {
  const q = f.q.trim().toLowerCase().replace(/^#/, '')
  return items.filter((item) => {
    if (
      q &&
      !item.subject.toLowerCase().includes(q) &&
      !String(item.ref).startsWith(q)
    )
      return false
    return facets.every((facet) => {
      const wanted = f.facets[facet.key] ?? []
      if (wanted.length === 0) return true
      const has = facet.values(item)
      return wanted.some((w) => has.includes(w))
    })
  })
}
