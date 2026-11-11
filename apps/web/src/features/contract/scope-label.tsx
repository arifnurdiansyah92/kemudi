import { useTranslation } from 'react-i18next'
import type { ScopeLabel } from '@/lib/kemudi-ai/queries'
import { cn } from '@/lib/utils'

// Meaning-only colour: in scope is done-teal, a CR is the red of "blocked
// from the sprint", unclear stays neutral until someone asks the client.
const dot: Record<ScopeLabel, string> = {
  in_baseline: 'bg-success',
  cr_candidate: 'bg-destructive',
  needs_clarification: 'bg-muted-foreground',
}

export function ScopeChip({
  label,
  className,
}: {
  label: ScopeLabel
  className?: string
}) {
  const { t } = useTranslation('contract')
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border bg-background px-2 py-0.5 text-xs font-medium whitespace-nowrap',
        className
      )}
    >
      <span aria-hidden className={cn('size-1.5 rounded-full', dot[label])} />
      {t(`labels.${label}`)}
    </span>
  )
}
