import { useTranslation } from 'react-i18next'
import type { ScanLevel, SkillSource } from '@/lib/kemudi-ai/agent'
import type { Finding, Severity } from '@/lib/kemudi-ai/skills'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'

export function SourceBadge({ source }: { source: SkillSource }) {
  const { t } = useTranslation('skills')
  return (
    <Badge variant='outline' className='font-normal'>
      {t(`source.${source}`)}
    </Badge>
  )
}

/** The worst scan finding. Medium and high carry the danger color; clean
 * and low stay neutral (the Meaning-Only Color rule). */
export function ScanBadge({ level }: { level: ScanLevel }) {
  const { t } = useTranslation('skills')
  const serious = level === 'medium' || level === 'high'
  return (
    <Badge
      variant='outline'
      className={cn(
        'font-normal',
        serious
          ? 'border-destructive/40 text-destructive'
          : 'text-muted-foreground'
      )}
    >
      {t(`scan.${level || 'clean'}`)}
    </Badge>
  )
}

function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation('skills')
  return (
    <Badge
      variant='outline'
      className={cn(
        'w-16 justify-center font-normal',
        severity === 'high' &&
          'border-transparent bg-destructive/10 text-destructive',
        severity === 'medium' && 'border-destructive/40 text-destructive',
        severity === 'low' && 'text-muted-foreground'
      )}
    >
      {t(`severity.${severity}`)}
    </Badge>
  )
}

/** Scan findings, worst first. */
export function FindingList({ findings }: { findings: Finding[] }) {
  const { t } = useTranslation('skills')
  const order = { high: 0, medium: 1, low: 2 }
  const sorted = [...findings].sort(
    (a, b) => order[a.severity] - order[b.severity]
  )
  return (
    <ul className='divide-y rounded-lg border'>
      {sorted.map((f, i) => (
        <li key={i} className='flex items-start gap-3 px-3 py-2'>
          <SeverityBadge severity={f.severity} />
          <div className='grid min-w-0 flex-1 gap-0.5'>
            <p className='text-sm'>
              {t(`rules.${f.rule}`, { defaultValue: f.rule })}
            </p>
            <p className='text-xs text-muted-foreground'>
              <span className='font-mono'>{f.path}</span>
              {f.line > 0 && ` · ${t('detail.line', { line: f.line })}`}
            </p>
            {f.line > 0 && f.excerpt && (
              <p className='truncate font-mono text-xs text-muted-foreground'>
                {f.excerpt}
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}
