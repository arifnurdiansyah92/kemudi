/**
 * Bahasa Indonesia and English, switchable per user.
 *
 * The language comes from, in order: the signed-in user's Taiga `lang`
 * (so emails from kemudi-back follow the same choice), the last choice on
 * this device, then the browser. See docs/i18n.md for the glossary and the
 * rules for writing strings.
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { defaultNS, resources } from './resources'

export const languages = ['id', 'en'] as const
export type Language = (typeof languages)[number]

const STORAGE_KEY = 'kemudi.lang'

/** Map any Taiga or browser locale code onto one we ship, if any. */
export function toLanguage(code: string | null | undefined): Language | null {
  const base = code?.toLowerCase().split(/[-_]/)[0]
  return languages.find((l) => l === base) ?? null
}

function stored(): Language | null {
  try {
    return toLanguage(localStorage.getItem(STORAGE_KEY))
  } catch {
    return null
  }
}

function initial(): Language {
  return (
    stored() ??
    navigator.languages.map(toLanguage).find((l) => l !== null) ??
    'en'
  )
}

function applyDocument(lng: string) {
  document.documentElement.lang = lng
}

i18n.use(initReactI18next).init({
  resources,
  lng: initial(),
  fallbackLng: 'en',
  supportedLngs: languages,
  defaultNS,
  ns: Object.keys(resources.en),
  interpolation: { escapeValue: false },
  returnNull: false,
})
applyDocument(i18n.language)
i18n.on('languageChanged', applyDocument)

/** Switch the UI language on this device. Callers sync it to the user. */
export function setLanguage(lng: Language) {
  try {
    localStorage.setItem(STORAGE_KEY, lng)
  } catch {
    // Storage unavailable: the choice lasts for this tab.
  }
  if (i18n.language !== lng) void i18n.changeLanguage(lng)
}

export function currentLanguage(): Language {
  return toLanguage(i18n.language) ?? 'en'
}

export default i18n
