import { useState } from 'react'
import type { Id } from '@/lib/taiga/types'
import type { Density } from './story-card'

const key = (projectId: Id) => `kemudi.kanban.folded.${projectId}`

function read(projectId: Id): Set<Id> {
  try {
    return new Set(JSON.parse(localStorage.getItem(key(projectId)) ?? '[]'))
  } catch {
    return new Set()
  }
}

/** Folded kanban columns, remembered per project on this device. */
export function useFolded(projectId: Id) {
  const [folded, setFolded] = useState(() => read(projectId))
  const toggle = (statusId: Id) =>
    setFolded((prev) => {
      const next = new Set(prev)
      if (next.has(statusId)) next.delete(statusId)
      else next.add(statusId)
      try {
        localStorage.setItem(key(projectId), JSON.stringify([...next]))
      } catch {
        // Storage unavailable: folding lasts for this visit only.
      }
      return next
    })
  return { folded, toggle }
}

const densityKey = (projectId: Id) => `kemudi.kanban.density.${projectId}`

/** Card density on this project's board, remembered on the device. */
export function useDensity(projectId: Id) {
  const [density, setDensity] = useState<Density>(() => {
    try {
      const v = localStorage.getItem(densityKey(projectId))
      return v === 'compact' || v === 'detailed' ? v : 'standard'
    } catch {
      return 'standard'
    }
  })
  const set = (d: Density) => {
    setDensity(d)
    try {
      localStorage.setItem(densityKey(projectId), d)
    } catch {
      // Storage unavailable: the choice lasts for this visit only.
    }
  }
  return { density, setDensity: set }
}
