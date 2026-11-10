import { describe, expect, it } from 'vitest'
import type { UserStory } from '@/lib/taiga/types'
import { between, forecastIndex, sumPoints } from './utils'

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

describe('forecastIndex', () => {
  const s = (...pts: (number | null)[]) =>
    pts.map((total_points) => ({ total_points }))

  it('marks the last story that fits the speed', () => {
    expect(forecastIndex(s(3, 5, 8, 2), 10)).toBe(1)
  })

  it('counts unestimated stories as free', () => {
    expect(forecastIndex(s(3, null, 5, 8), 8)).toBe(2)
  })

  it('draws no line without a speed or when everything fits', () => {
    expect(forecastIndex(s(3, 5), 0)).toBe(-1)
    expect(forecastIndex(s(3, 5), 20)).toBe(-1)
  })
})
