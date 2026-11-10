import { useState } from 'react'
import type { Id } from '@/lib/taiga/types'

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
