import { useEffect } from 'react'
import { useRouter } from '@tanstack/react-router'
import { isLegacyPath } from '@/lib/legacy-urls'

/**
 * Same-origin links inside server-rendered Markdown (wiki links, #ref
 * mentions) and old taiga-front paths open inside the app instead of
 * reloading the page.
 */
export function useInAppLinks() {
  const router = useRouter()
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0) return
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      const anchor = (e.target as Element | null)?.closest?.('a')
      if (
        !anchor ||
        anchor.target === '_blank' ||
        anchor.hasAttribute('download')
      )
        return
      let url: URL
      try {
        url = new URL(anchor.href)
      } catch {
        return
      }
      // Taiga marks its own links (wiki pages, #ref mentions) with
      // class="reference" and writes them with the backend's site domain,
      // which can differ from where this UI is served.
      const taigaReference =
        anchor.classList.contains('reference') && isLegacyPath(url.pathname)
      if (url.origin !== window.location.origin && !taigaReference) return
      const inRichText = !!anchor.closest('.rich-text')
      if (!inRichText && !isLegacyPath(url.pathname)) return
      e.preventDefault()
      router.history.push(url.pathname + url.search + url.hash)
    }
    document.addEventListener('click', onClick)
    return () => document.removeEventListener('click', onClick)
  }, [router])
}
