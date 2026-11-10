import { describe, expect, it } from 'vitest'
import type { UserStory } from '@/lib/taiga/types'
import { between, sumPoints } from './utils'

describe('between', () => {
  it('sits halfway between two neighbours', () => {
    expect(between(10, 20)).toBe(15)
  })

  it('goes just past the only neighbour at either end', () => {
    expect(between(10, undefined)).toBe(11)
    expect(between(undefined, 10)).toBe(9)
  })

  it('handles an empty list', () => {
    expect(between()).toBe(0)
  })
})

describe('sumPoints', () => {
  it('adds points and skips unestimated stories', () => {
    const stories = [
      { total_points: 3 },
      { total_points: null },
      { total_points: 5.5 },
    ] as UserStory[]
    expect(sumPoints(stories)).toBe(8.5)
  })
})
