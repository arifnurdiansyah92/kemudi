import { TriangleAlert, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ScanLevel } from '@/lib/kemudi-ai/agent'
import type { SkillProblem } from '@/lib/kemudi-ai/skills'
import { FindingList } from './badges'

/**
 * Who gets a new version of a skill: the roles that list it, on their next
 * run, when the skill is enabled. Shown wherever a new version is confirmed.
 */
export function RolloutNote({
  usedBy,
  enabled,
}: {
  usedBy: number
  enabled: boolean
}) {
  const { t } = useTranslation('skills')
  return (
    <p className='flex items-start gap-2 text-sm text-muted-foreground'>
      <Users className='mt-0.5 size-4 shrink-0' aria-hidden />
      {enabled || usedBy === 0
        ? t('rollout.next', { count: usedBy })
        : t('rollout.waiting', { count: usedBy })}
    </p>
  )
}

/**
 * The server refused a new version (`findings_rise`): its scan is worse than
 * the current version's and roles run the skill. Lists the findings; the
 * caller offers "Use this version anyway".
 */
export function FindingsRise({ problem: p }: { problem: SkillProblem }) {
  const { t } = useTranslation('skills')
  const level = (l: ScanLevel | undefined) =>
    t(`rollout.level.${l || 'clean'}` as const)
  return (
    <div
      role='alert'
      className='grid gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm'
    >
      <p className='flex items-start gap-1.5 font-medium text-destructive'>
        <TriangleAlert className='mt-0.5 size-4 shrink-0' aria-hidden />
        {t('rollout.rise', {
          count: p.used_by?.length ?? 0,
          worst: level(p.worst),
          previous: level(p.previous),
        })}
      </p>
      {(p.findings?.length ?? 0) > 0 && (
        <div className='max-h-60 overflow-auto'>
          <FindingList findings={p.findings!} />
        </div>
      )}
    </div>
  )
}
