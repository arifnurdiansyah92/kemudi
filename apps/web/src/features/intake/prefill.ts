/**
 * A one-time handoff of requirements text into Intake from another page of
 * the same project (product research sends its feature suggestions here).
 * It lives in sessionStorage, so it stays in this tab and survives the
 * navigation; Intake reads it once on mount and clears it.
 */
const KEY = 'kemudi.intake.prefill'

type Prefill = { slug: string; text: string }

export function setIntakePrefill(slug: string, text: string) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ slug, text } as Prefill))
  } catch {
    // Storage unavailable: Intake opens empty.
  }
}

/** The text waiting for this project, or `''`. Does not clear it. */
export function readIntakePrefill(slug: string) {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return ''
    const parsed = JSON.parse(raw) as Partial<Prefill>
    return parsed.slug === slug && typeof parsed.text === 'string'
      ? parsed.text
      : ''
  } catch {
    return ''
  }
}

export function clearIntakePrefill() {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // Nothing to clear.
  }
}
