import { Link } from '@tanstack/react-router'
import { FileSearch, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useCrVerdict,
  useRunCrCheck,
  useTicketChecks,
  type TicketKind,
} from '@/lib/kemudi-ai/queries'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { CheckResult } from './check-result'

/**
 * "Check against contract" on a story or issue: the latest AI suggestion,
 * the PM's verdict and earlier checks. Without an approved baseline it
 * points admins at the Contract page and stays out of everyone else's way;
 * when Kemudi AI is unreachable it renders nothing.
 */
export function ContractCheck({
  project,
  kind,
  itemRef,
}: {
  project: Project
  kind: TicketKind
  itemRef: number
}) {
  const { t } = useTranslation('contract')
  const isAdmin = project.i_am_admin
  const checks = useTicketChecks(project.slug, kind, itemRef)
  const run = useRunCrCheck(project.slug)
  const verdict = useCrVerdict(project.slug)

  if (checks.isError) return null
  if (checks.isPending)
    return (
      <Section title={t('check.title')}>
        <Skeleton className='h-16' />
      </Section>
    )
  const { baseline, checks: list } = checks.data
  if (!baseline) {
    if (!isAdmin) return null
    return (
      <Section title={t('check.title')}>
        <p className='text-sm text-muted-foreground'>
          {t('check.noBaseline')}{' '}
          <Link
            to='/p/$slug/contract'
            params={{ slug: project.slug }}
            className='font-medium text-foreground underline-offset-4 hover:underline'
          >
            {t('check.setUp')}
          </Link>
        </p>
      </Section>
    )
  }
  const [latest, ...earlier] = list

  return (
    <Section title={t('check.title')}>
      <div className='grid gap-4'>
        {latest ? (
          <CheckResult
            check={latest}
            canReview={isAdmin}
            busy={verdict.isPending}
            onVerdict={(v) => verdict.mutate({ id: latest.id, ...v })}
          />
        ) : (
          <p className='text-sm text-muted-foreground'>
            {isAdmin ? t('check.empty') : t('check.emptyMember')}
          </p>
        )}
        {isAdmin && (
          <div className='flex flex-wrap items-center gap-3'>
            <Button
              size='sm'
              variant={latest ? 'outline' : 'default'}
              disabled={run.isPending}
              onClick={() => run.mutate({ kind, ref: itemRef })}
            >
              {run.isPending ? (
                <Loader2 className='animate-spin' />
              ) : (
                <FileSearch />
              )}
              {latest ? t('check.rerun') : t('check.run')}
            </Button>
            {run.isPending && (
              <span role='status' className='text-xs text-muted-foreground'>
                {t('check.running', { version: baseline.number })}
              </span>
            )}
          </div>
        )}
        {earlier.length > 0 && (
          <details className='text-sm'>
            <summary className='cursor-pointer text-muted-foreground'>
              {t('check.history', { count: earlier.length })}
            </summary>
            <ol className='mt-3 grid gap-4'>
              {earlier.map((c) => (
                <li key={c.id} className='rounded-md border p-3'>
                  <CheckResult
                    check={c}
                    canReview={isAdmin}
                    busy={verdict.isPending}
                    onVerdict={(v) => verdict.mutate({ id: c.id, ...v })}
                  />
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
    </Section>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className='border-t px-6 py-5'>
      <h3 className='mb-3 text-sm font-semibold'>{title}</h3>
      {children}
    </section>
  )
}
