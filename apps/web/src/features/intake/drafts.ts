import type { IntakeDraftIn, IntakeDraftOut } from '@/lib/kemudi-ai/agent'

/** A draft as the PM edits it: the server's draft plus local choices. */
export type DraftState = IntakeDraftOut & {
  key: string
  hold: boolean
  /** Edited since drafting: the server rechecks Ready on create. */
  edited: boolean
  /** Keys of the drafts this one waits for (keys survive a removed row). */
  after: string[]
}

export const SUBJECT_MIN = 3

export function toState(drafts: IntakeDraftOut[]): DraftState[] {
  const stamp = Date.now()
  return drafts.map((d, i) => ({
    ...d,
    key: `${stamp}-${i}`,
    hold: false,
    edited: false,
    after: (d.depends_on ?? [])
      .filter((n) => n >= 1 && n <= i)
      .map((n) => `${stamp}-${n - 1}`),
  }))
}

/** The row numbers (the first is 1) a draft waits for, as the list stands
 * now: a removed draft is no longer waited for. */
export function afterNumbers(
  draft: DraftState,
  drafts: DraftState[]
): number[] {
  const own = drafts.findIndex((d) => d.key === draft.key)
  return draft.after
    .map((key) => drafts.findIndex((d) => d.key === key) + 1)
    .filter((n) => n >= 1 && n <= own)
    .sort((a, b) => a - b)
}

/** The create body: blank criteria dropped, local-only fields left out. */
export function draftsBody(drafts: DraftState[]): IntakeDraftIn[] {
  return drafts.map((d) => ({
    subject: d.subject.trim(),
    description: d.description.trim(),
    criteria: d.criteria.map((c) => c.trim()).filter(Boolean),
    area: d.area,
    hold: d.hold,
    depends_on: afterNumbers(d, drafts),
  }))
}
