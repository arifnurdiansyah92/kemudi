import type { IntakeDraftIn, IntakeDraftOut } from '@/lib/kemudi-ai/agent'

/** A draft as the PM edits it: the server's draft plus local choices. */
export type DraftState = IntakeDraftOut & {
  key: string
  hold: boolean
  /** Edited since drafting: the server rechecks Ready on create. */
  edited: boolean
}

export const SUBJECT_MIN = 3

export function toState(drafts: IntakeDraftOut[]): DraftState[] {
  const stamp = Date.now()
  return drafts.map((d, i) => ({
    ...d,
    key: `${stamp}-${i}`,
    hold: false,
    edited: false,
  }))
}

/** The create body: blank criteria dropped, local-only fields left out. */
export function draftsBody(drafts: DraftState[]): IntakeDraftIn[] {
  return drafts.map((d) => ({
    subject: d.subject.trim(),
    description: d.description.trim(),
    criteria: d.criteria.map((c) => c.trim()).filter(Boolean),
    area: d.area,
    hold: d.hold,
  }))
}
