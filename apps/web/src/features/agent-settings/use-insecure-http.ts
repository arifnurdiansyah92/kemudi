import { useState } from 'react'
import { INSECURE_REFUSAL, isInsecureHttp } from './providers'

/**
 * Plain http to a public address needs an explicit acknowledgement, given
 * per URL: changing the URL asks again. The notice shows when the URL looks
 * public here, when the server refused it as such, or for the saved insecure
 * URL (already acknowledged).
 */
export function useInsecureHttp(
  url: string,
  saved: { url: string; insecure: boolean }
) {
  const [ackedUrl, setAckedUrl] = useState<string | null>(
    saved.insecure ? saved.url : null
  )
  const [refusedUrl, setRefusedUrl] = useState<string | null>(null)
  const http = /^http:\/\//i.test(url)
  const shown =
    http &&
    (isInsecureHttp(url) ||
      refusedUrl === url ||
      (saved.insecure && url === saved.url))
  const ack = shown && ackedUrl === url
  return {
    shown,
    ack,
    /** Shown and not ticked: saving or testing would be refused. */
    blocked: shown && !ack,
    setAck: (checked: boolean) => setAckedUrl(checked ? url : null),
    /** What to add to a request body. */
    flag: ack ? { allow_insecure_http: true as const } : {},
    /** Shows the notice when the server refused the URL as public http. */
    noteError: (message: string) => {
      if (http && message.includes(INSECURE_REFUSAL)) setRefusedUrl(url)
    },
  }
}
