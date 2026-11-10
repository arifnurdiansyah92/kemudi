import type { UserStory } from '@/lib/taiga/types'

/** Sum of story points, skipping unestimated stories. */
export function sumPoints(stories: UserStory[]) {
  return stories.reduce((total, s) => total + (s.total_points ?? 0), 0)
}

/** A sortable position between two neighbours, for optimistic ordering. */
export function between(before?: number, after?: number) {
  if (before === undefined && after === undefined) return 0
  if (before === undefined) return (after as number) - 1
  if (after === undefined) return before + 1
  return (before + after) / 2
}
