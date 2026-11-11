/**
 * Locale formats, not just words: dates, numbers, Rupiah and Indonesian
 * time zones. Everything reads the current UI language, so call these
 * during render (components re-render on language change through
 * useTranslation) or use the `useFormat` hook.
 */
import {
  format as fnsFormat,
  formatDistanceToNowStrict,
  isSameYear,
  parseISO,
} from 'date-fns'
import { enGB, id as idLocale } from 'date-fns/locale'
import { useTranslation } from 'react-i18next'
import i18n, { currentLanguage, type Language } from './index'

const dateLocales = { id: idLocale, en: enGB }
/** BCP 47 tags for Intl. English uses en-GB for "11 Nov 2026" day-first dates. */
const intlLocales: Record<Language, string> = { id: 'id-ID', en: 'en-GB' }

type DateInput = string | Date

function toDate(d: DateInput) {
  return typeof d === 'string'
    ? d.length === 10
      ? parseISO(d)
      : new Date(d)
    : d
}

const patterns = {
  /** 11 Nov 2026 */
  date: 'd MMM yyyy',
  /** 11 Nov */
  dayMonth: 'd MMM',
  /** 11 Nov 2026, 14.05 (id) / 11 Nov 2026, 14:05 (en) */
  dateTime: 'd MMM yyyy, HH.mm',
  /** Rabu, 11 November 2026 */
  long: 'EEEE, d MMMM yyyy',
} as const

export type DatePattern = keyof typeof patterns

export function formatDate(d: DateInput, pattern: DatePattern = 'date') {
  const lng = currentLanguage()
  let p: string = patterns[pattern]
  if (lng === 'en') p = p.replace('HH.mm', 'HH:mm')
  return fnsFormat(toDate(d), p, { locale: dateLocales[lng] })
}

/** "4 – 18 Nov 2026"-style ranges; the year shows once when both share it. */
export function formatDateRange(start: DateInput, end: DateInput) {
  const s = toDate(start)
  const e = toDate(end)
  const left = isSameYear(s, e)
    ? formatDate(s, 'dayMonth')
    : formatDate(s, 'date')
  return `${left} – ${formatDate(e, 'date')}`
}

/** "3 menit yang lalu" / "3 minutes ago"; a few seconds either way is "just now". */
export function timeAgo(d: DateInput) {
  const date = toDate(d)
  if (Date.now() - date.getTime() < 45_000) return i18n.t('common:time.justNow')
  return formatDistanceToNowStrict(date, {
    addSuffix: true,
    locale: dateLocales[currentLanguage()],
  })
}

/** 1.000,5 (id) / 1,000.5 (en) */
export function formatNumber(n: number, options?: Intl.NumberFormatOptions) {
  return new Intl.NumberFormat(intlLocales[currentLanguage()], options).format(
    n
  )
}

/** Rp1.500.000 in both languages; English keeps Indonesian money conventions readable. */
export function formatRupiah(amount: number) {
  const n = new Intl.NumberFormat(intlLocales[currentLanguage()], {
    maximumFractionDigits: 0,
  }).format(amount)
  return `Rp${n}`
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${formatNumber(bytes)} B`
  if (bytes < 1024 ** 2)
    return `${formatNumber(bytes / 1024, { maximumFractionDigits: 0 })} KB`
  return `${formatNumber(bytes / 1024 ** 2, { maximumFractionDigits: 1 })} MB`
}

/** Indonesia's three zones go by their local names, not GMT offsets. */
const indonesianZones: Record<string, string> = {
  'Asia/Jakarta': 'WIB',
  'Asia/Pontianak': 'WIB',
  'Asia/Makassar': 'WITA',
  'Asia/Jayapura': 'WIT',
}

/** "14.05 WIB"; other zones fall back to Intl's short name. */
export function formatTime(d: DateInput, timeZone?: string) {
  const lng = currentLanguage()
  const zone = timeZone || Intl.DateTimeFormat().resolvedOptions().timeZone
  const time = new Intl.DateTimeFormat(intlLocales[lng], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: zone,
  }).format(toDate(d))
  const name =
    indonesianZones[zone] ??
    new Intl.DateTimeFormat(intlLocales[lng], {
      timeZone: zone,
      timeZoneName: 'short',
    })
      .formatToParts(toDate(d))
      .find((p) => p.type === 'timeZoneName')?.value
  return name ? `${time} ${name}` : time
}

export function timeZoneLabel(zone: string) {
  const short = indonesianZones[zone]
  const city = zone.split('/').pop()?.replace(/_/g, ' ') ?? zone
  return short ? `${city} (${short})` : zone.replace(/_/g, ' ')
}

/** The formatters, re-bound on language change. */
export function useFormat() {
  useTranslation()
  return {
    date: formatDate,
    dateRange: formatDateRange,
    timeAgo,
    number: formatNumber,
    rupiah: formatRupiah,
    bytes: formatBytes,
    time: formatTime,
  }
}
