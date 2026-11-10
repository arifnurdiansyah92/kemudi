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

/**
 * Index of the last story that still fits a sprint of `speed` points,
 * taking stories in order; -1 when the speed is unknown or everything fits
 * (no line to draw).
 */
export function forecastIndex(
  stories: { total_points: number | null }[],
  speed: number
) {
  if (speed <= 0) return -1
  let total = 0
  let last = -1
  stories.forEach((s, i) => {
    total += s.total_points ?? 0
    if (total <= speed) last = i
  })
  return last === stories.length - 1 ? -1 : last
}
