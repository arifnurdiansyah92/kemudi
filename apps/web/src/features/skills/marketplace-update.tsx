import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Check, ExternalLink, RefreshCw, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  skillProblem,
  useCheckUpdate,
  useDecideVersion,
  type PendingVersion,
  type SkillDetail,
  type SkillProblem,
  type UpdateResult,
} from '@/lib/kemudi-ai/skills'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { FindingList, ScanBadge } from './badges'

/** A marketplace skill's origin (repo@sha), "Check for update" and the
 * pending version awaiting approval. */
export function MarketplaceOrigin({ skill: s }: { skill: SkillDetail }) {
  const { t } = useTranslation('skills')
  const f = useFormat()
  const check = useCheckUpdate()
  const [result, setResult] = useState<UpdateResult | null>(null)
  const o = s.origin
  const status = result?.status ?? o.check_status
  const sha = result?.sha?.slice(0, 7) ?? ''
  const statusText =
    status === 'up_to_date'
      ? sha
        ? t('update.upToDateAt', { sha })
        : t('update.upToDate')
      : status === 'pending'
        ? t('update.pendingFound')
        : status === 'rejected'
          ? t('update.rejectedBefore')
          : status === 'invalid'
            ? t('update.invalid')
            : (result?.message ?? t('update.missing'))

  const doCheck = () =>
    check.mutate(s.slug, {
      onSuccess: (r) => setResult(r.result),
      onError: (err) => {
        const p = skillProblem(err)
        toast.error(t('update.checkFailed'), {
          description: p.problems.join(' ') || p.message,
        })
      },
    })

  return (
    <section
      className='grid gap-3 rounded-lg border px-3 py-3'
      aria-labelledby='skill-origin'
    >
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <div className='grid min-w-0 flex-1 gap-1'>
          <h3 id='skill-origin' className='text-sm font-medium'>
            {t('update.origin')}
          </h3>
          <p className='text-xs text-muted-foreground'>
            {s.origin_url ? (
              <a
                href={s.origin_url}
                target='_blank'
                rel='noreferrer noopener'
                className='inline-flex items-center gap-1 font-mono underline-offset-4 hover:text-foreground hover:underline'
              >
                {o.repo}@{o.sha?.slice(0, 7)}
                <ExternalLink className='size-3' aria-hidden />
              </a>
            ) : (
              <span className='font-mono'>{o.repo}</span>
            )}
          </p>
          <p className='text-xs text-muted-foreground'>
            {t('update.fromPlugin', {
              plugin: o.plugin ?? '',
              marketplace: o.marketplace ?? o.repo ?? '',
            })}
            {o.path && (
              <>
                {' · '}
                <span className='font-mono'>{o.path}</span>
              </>
            )}
          </p>
        </div>
        <Button
          size='sm'
          variant='outline'
          onClick={doCheck}
          disabled={check.isPending}
        >
          <RefreshCw
            className={check.isPending ? 'animate-spin' : undefined}
            aria-hidden
          />
          {check.isPending ? t('update.checking') : t('update.check')}
        </Button>
      </div>
      {status && (
        <p role='status' className='text-xs text-muted-foreground'>
          {statusText}
          {o.checked_at && !result && (
            <> · {t('update.checkedAt', { when: f.timeAgo(o.checked_at) })}</>
          )}
        </p>
      )}
      {result?.status === 'invalid' && result.problems?.length ? (
        <ul className='list-disc ps-5 text-xs text-destructive'>
          {result.problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : null}
      {(s.pending ?? []).map((p) => (
        <PendingCard key={p.version} skill={s} pending={p} />
      ))}
    </section>
  )
}

function PendingCard({
  skill: s,
  pending: p,
}: {
  skill: SkillDetail
  pending: PendingVersion
}) {
  const { t } = useTranslation('skills')
  const f = useFormat()
  const decide = useDecideVersion()
  const [rise, setRise] = useState<SkillProblem | null>(null)
  const changes =
    p.diff.added.length + p.diff.removed.length + p.diff.changed.length

  const run = (decision: 'approve' | 'reject', acceptFindings = false) =>
    decide.mutate(
      {
        slug: s.slug,
        version: p.version,
        decision,
        sha256: p.sha256,
        acceptFindings,
      },
      {
        onSuccess: (d) => {
          setRise(null)
          toast.success(
            decision === 'approve'
              ? t('update.approved', { version: p.version })
              : t('update.rejected', { version: p.version }),
            d.disabled_now
              ? { description: t('update.disabledNow') }
              : undefined
          )
        },
        onError: (err) => {
          const prob = skillProblem(err)
          if (prob.code === 'findings_rise') {
            setRise(prob)
            return
          }
          setRise(null)
          toast.error(prob.message)
        },
      }
    )

  return (
    <article
      className='grid gap-3 rounded-lg border bg-muted/30 px-3 py-3'
      aria-label={t('update.pendingTitle', { version: p.version })}
    >
      <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
        <h4 className='text-sm font-medium'>
          {t('update.pendingTitle', { version: p.version })}
        </h4>
        <Badge variant='outline' className='font-normal'>
          {t('detail.pending')}
        </Badge>
        <ScanBadge level={p.scan_level} />
        <span className='text-xs text-muted-foreground'>
          {t('update.fromCommit', {
            sha: p.origin.sha?.slice(0, 7) ?? '',
            when: f.timeAgo(p.created_at),
          })}
        </span>
      </div>
      <p className='text-xs text-muted-foreground'>{t('update.pendingHint')}</p>

      <div className='grid gap-1'>
        <h5 className='text-xs font-medium'>
          {t('update.changes', { count: changes })}
        </h5>
        <ul className='grid gap-0.5 font-mono text-xs'>
          {p.diff.added.map((x) => (
            <DiffLine key={`a${x}`} kind='added' path={x} />
          ))}
          {p.diff.changed.map((x) => (
            <DiffLine key={`c${x}`} kind='changed' path={x} />
          ))}
          {p.diff.removed.map((x) => (
            <DiffLine key={`r${x}`} kind='removed' path={x} />
          ))}
        </ul>
      </div>

      {p.findings.length > 0 && (
        <div className='grid gap-1'>
          <h5 className='text-xs font-medium'>{t('detail.tabs.findings')}</h5>
          <FindingList findings={p.findings} />
        </div>
      )}

      <div className='flex flex-wrap gap-2'>
        <Button
          size='sm'
          onClick={() => run('approve')}
          disabled={decide.isPending}
        >
          <Check />
          {t('update.approve')}
        </Button>
        <Button
          size='sm'
          variant='ghost'
          onClick={() => run('reject')}
          disabled={decide.isPending}
        >
          <X />
          {t('update.reject')}
        </Button>
      </div>

      <ConfirmDialog
        open={rise !== null}
        onOpenChange={(o) => !o && setRise(null)}
        title={t('update.riseTitle')}
        desc={t('update.riseBody', {
          to: t(`scan.${rise?.worst || 'clean'}`),
          from: t(`scan.${rise?.previous || 'clean'}`),
          count: rise?.used_by?.length ?? 0,
        })}
        confirmText={t('update.approveAnyway')}
        destructive
        isLoading={decide.isPending}
        handleConfirm={() => run('approve', true)}
      />
    </article>
  )
}

function DiffLine({
  kind,
  path,
}: {
  kind: 'added' | 'changed' | 'removed'
  path: string
}) {
  const { t } = useTranslation('skills')
  const mark = { added: '+', changed: '~', removed: '−' }[kind]
  return (
    <li className='flex gap-2'>
      <span
        className={
          kind === 'removed' ? 'text-destructive' : 'text-muted-foreground'
        }
        aria-hidden
      >
        {mark}
      </span>
      <span className='sr-only'>{t(`update.diff.${kind}`)}</span>
      <span className='min-w-0 truncate'>{path}</span>
    </li>
  )
}
