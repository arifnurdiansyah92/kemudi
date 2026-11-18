import { useTranslation } from 'react-i18next'
import type { ProductRunStatus } from '@/lib/kemudi-ai/product'
import { cn } from '@/lib/utils'

const dots: Record<ProductRunStatus, string> = {
  queued: 'bg-muted-foreground/50',
  running: 'bg-primary motion-safe:animate-pulse',
  done: 'bg-success',
  failed: 'bg-destructive',
}

/** The status in words, with a meaning-only dot. */
export function StatusBadge({
  status,
  className,
}: {
  status: ProductRunStatus
  className?: string
}) {
  const { t } = useTranslation('agent')
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 text-xs font-medium',
        className
      )}
    >
      <span
        aria-hidden
        className={cn('size-2 shrink-0 rounded-full', dots[status])}
      />
      {t(`research.status.${status}`)}
    </span>
  )
}
