import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, GitMerge, Loader2, XCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  AWAITING_MERGE_TAG,
  isMergePending,
  useMergeStory,
  useRepos,
  useStoryAgent,
} from '@/lib/kemudi-ai/agent'
import type { Item, Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/confirm-dialog'

/**
 * Merge on approve: a strip on a story that passed QA and carries
 * awaiting-merge, for project admins. After the click it stays to show how
 * the merge ended, even once the tag changes.
 */
export function MergeAction({
  project,
  story,
}: {
  project: Project
  story: Item
}) {
  const tagged = (story.tags ?? []).some(
    ([name]) => name === AWAITING_MERGE_TAG
  )
  const [watching, setWatching] = useState(false)
  const show = project.i_am_admin && (tagged || watching)
  const agent = useStoryAgent(project.slug, story.id, show)

  if (!show || !agent.data || agent.data.merge_mode !== 'approve') return null
  const { can_merge, merge_state } = agent.data
  if (!can_merge && !watching && !isMergePending(merge_state)) {
    // A failed merge with no way to retry still says why.
    if (merge_state !== 'failed') return null
  }
  return (
    <MergeStrip
      project={project}
      story={story}
      data={agent.data}
      onRequested={() => setWatching(true)}
    />
  )
}

function MergeStrip({
  project,
  story,
  data,
  onRequested,
}: {
  project: Project
  story: Item
  data: NonNullable<ReturnType<typeof useStoryAgent>['data']>
  onRequested: () => void
}) {
  const { t } = useTranslation('agent')
  const qc = useQueryClient()
  const merge = useMergeStory(project.slug, story.id)
  const repos = useRepos(project.slug)
  const [confirming, setConfirming] = useState(false)
  const { job, can_merge, merge_state, merge_error } = data
  const branch = job?.branch ?? ''
  const repo = repos.data?.find((r) => r.id === job?.repo_id)
  const target = repo?.default_branch ?? t('merge.anyBranch')
  const pending = isMergePending(merge_state)

  // When a merge this sheet watched settles, the story's tags have changed.
  const was = useRef(merge_state)
  useEffect(() => {
    if (isMergePending(was.current) && !isMergePending(merge_state)) {
      qc.invalidateQueries({ queryKey: ['item', project.id] })
      qc.invalidateQueries({ queryKey: ['stories', project.id] })
    }
    was.current = merge_state
  }, [merge_state, project.id, qc])

  const code = (s: string) => (
    <code className='rounded bg-muted px-1 py-0.5 font-mono text-xs'>{s}</code>
  )

  return (
    <div
      role='status'
      className='flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-6 py-3 text-sm'
    >
      <div className='flex min-w-0 flex-1 items-start gap-2'>
        {merge_state === 'merged' ? (
          <>
            <CheckCircle2 className='mt-0.5 size-4 shrink-0 text-success' />
            <p>
              {t('mergeButton.merged', { target })}{' '}
              {job?.merged_sha && code(job.merged_sha.slice(0, 7))}
            </p>
          </>
        ) : merge_state === 'failed' ? (
          <>
            <XCircle className='mt-0.5 size-4 shrink-0 text-destructive' />
            <p className='text-destructive'>
              {t('mergeButton.failed', {
                reason: merge_error || t('mergeButton.noReason'),
              })}
            </p>
          </>
        ) : pending ? (
          <>
            <Loader2 className='mt-0.5 size-4 shrink-0 animate-spin text-muted-foreground' />
            <p>
              {merge_state === 'merging'
                ? t('mergeButton.merging', { target })
                : t('mergeButton.requested')}
            </p>
          </>
        ) : (
          <>
            <GitMerge className='mt-0.5 size-4 shrink-0 text-muted-foreground' />
            <p className='min-w-0 break-words'>
              {t('mergeButton.summary', { branch })}
            </p>
          </>
        )}
      </div>
      {can_merge && !pending && (
        <Button
          size='sm'
          variant={merge_state === 'failed' ? 'outline' : 'default'}
          disabled={merge.isPending}
          onClick={() => setConfirming(true)}
        >
          {merge.isPending ? (
            <Loader2 className='animate-spin' />
          ) : (
            <GitMerge />
          )}
          {merge_state === 'failed'
            ? t('mergeButton.retry')
            : t('mergeButton.action')}
        </Button>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t('mergeButton.confirm.title')}
        desc={<p>{t('mergeButton.confirm.body', { branch, target })}</p>}
        confirmText={t('mergeButton.confirm.action', { target })}
        isLoading={merge.isPending}
        handleConfirm={() =>
          merge.mutate(undefined, {
            onSuccess: () => {
              onRequested()
              setConfirming(false)
            },
            onError: () => setConfirming(false),
          })
        }
      />
    </div>
  )
}
