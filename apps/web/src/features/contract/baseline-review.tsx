import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Loader2, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useApproveBaseline,
  useGenerateDraft,
  useSaveDraft,
  type BaselineItem,
  type BaselineVersion,
  type ContractState,
} from '@/lib/kemudi-ai/queries'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'

const kinds = ['epic', 'story', 'obligation', 'term'] as const

export function BaselineReview({
  slug,
  state,
  isAdmin,
}: {
  slug: string
  state: ContractState
  isAdmin: boolean
}) {
  const { t } = useTranslation('contract')
  const format = useFormat()
  const generate = useGenerateDraft(slug)
  const approve = useApproveBaseline(slug)
  const [confirming, setConfirming] = useState(false)
  const draft = state.baseline?.draft
  const approved = state.baseline?.approved
  const nextVersion = (approved?.number ?? 0) + 1

  if (!state.contract)
    return (
      <p className='text-sm text-muted-foreground'>
        {t('baseline.needsContract')}
      </p>
    )

  return (
    <div className='grid gap-8'>
      <div className='flex flex-wrap items-start justify-between gap-3'>
        <p className='max-w-2xl text-sm text-muted-foreground'>
          {t('baseline.description')}
        </p>
        {isAdmin && (
          <div className='flex flex-wrap gap-2'>
            <Button
              variant={draft ? 'outline' : 'default'}
              size='sm'
              disabled={generate.isPending}
              onClick={() => generate.mutate()}
            >
              {generate.isPending && <Loader2 className='animate-spin' />}
              {draft ? t('baseline.regenerate') : t('baseline.generate')}
            </Button>
            {draft && draft.items.length > 0 && (
              <Button size='sm' onClick={() => setConfirming(true)}>
                {t('baseline.approve')}
              </Button>
            )}
          </div>
        )}
      </div>
      {generate.isPending && (
        <p role='status' className='text-sm text-muted-foreground'>
          {t('baseline.generating')}
        </p>
      )}

      {draft ? (
        <section className='grid gap-3'>
          <h2 className='flex items-center gap-2 text-base font-semibold'>
            {t('baseline.draft')}
            <span className='rounded-full border px-2 py-0.5 text-xs font-medium text-muted-foreground'>
              {t('suggestion')}
            </span>
          </h2>
          <DraftEditor
            key={draft.id + ':' + draft.items.length}
            slug={slug}
            draft={draft}
            isAdmin={isAdmin}
          />
        </section>
      ) : (
        !approved && (
          <p className='text-sm text-muted-foreground'>
            {t('baseline.noDraft')}
          </p>
        )
      )}

      {approved && (
        <section className='grid gap-3'>
          <h2 className='text-base font-semibold'>
            {t('baseline.approved', {
              version: approved.number,
              by: approved.approved_by ?? '',
              date: approved.approved_at
                ? format.date(approved.approved_at)
                : '',
            })}
          </h2>
          <ItemList items={approved.items} />
          {state.baseline && state.baseline.history.length > 1 && (
            <details className='text-sm'>
              <summary className='cursor-pointer text-muted-foreground'>
                {t('baseline.history')}
              </summary>
              <ul className='mt-2 grid gap-1'>
                {state.baseline.history.map((v) => (
                  <li key={v.id}>
                    {t('baseline.approved', {
                      version: v.number,
                      by: v.approved_by ?? '',
                      date: v.approved_at ? format.date(v.approved_at) : '',
                    })}
                    {' · '}
                    {t('baseline.items', { count: v.items.length })}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t('baseline.approveTitle')}
        desc={t('baseline.approveDesc', { version: nextVersion })}
        confirmText={t('baseline.approve')}
        isLoading={approve.isPending}
        handleConfirm={() =>
          approve.mutate(undefined, { onSuccess: () => setConfirming(false) })
        }
      />
    </div>
  )
}

function DraftEditor({
  slug,
  draft,
  isAdmin,
}: {
  slug: string
  draft: BaselineVersion
  isAdmin: boolean
}) {
  const { t } = useTranslation('contract')
  const save = useSaveDraft(slug)
  const [items, setItems] = useState(draft.items)
  const dirty = JSON.stringify(items) !== JSON.stringify(draft.items)
  const update = (ref: string, patch: Partial<BaselineItem>) =>
    setItems(items.map((i) => (i.ref === ref ? { ...i, ...patch } : i)))

  if (!isAdmin) return <ItemList items={draft.items} />

  return (
    <div className='grid gap-6'>
      {kinds.map((kind) => {
        const group = items.filter((i) => i.kind === kind)
        if (!group.length) return null
        return (
          <div key={kind} className='grid gap-2'>
            <h3 className='text-sm font-semibold'>
              {t(`baseline.kinds.${kind}`)}{' '}
              <span className='font-normal text-muted-foreground'>
                ({group.length})
              </span>
            </h3>
            <ul className='divide-y rounded-lg border bg-card'>
              {group.map((item) => (
                <li
                  key={item.ref}
                  className='grid gap-2 p-3 sm:grid-cols-[3rem_1fr_auto]'
                >
                  <span className='pt-2 text-xs text-muted-foreground tabular-nums'>
                    {item.ref}
                  </span>
                  <div className='grid min-w-0 gap-2'>
                    <Input
                      aria-label={t('baseline.titleLabel')}
                      value={item.title}
                      onChange={(e) =>
                        update(item.ref, { title: e.target.value })
                      }
                      className='h-8 font-medium'
                    />
                    <Textarea
                      aria-label={t('baseline.descriptionLabel')}
                      rows={2}
                      value={item.description}
                      onChange={(e) =>
                        update(item.ref, { description: e.target.value })
                      }
                      className='min-h-0 text-sm'
                    />
                    {item.kind === 'story' && (
                      <Textarea
                        aria-label={t('baseline.acceptance')}
                        rows={Math.max(2, item.acceptance.length)}
                        value={item.acceptance.join('\n')}
                        onChange={(e) =>
                          update(item.ref, {
                            acceptance: e.target.value.split('\n'),
                          })
                        }
                        className='min-h-0 text-sm'
                      />
                    )}
                    <Clauses clauses={item.clauses} />
                  </div>
                  <Button
                    variant='ghost'
                    size='icon'
                    className='size-8'
                    aria-label={t('baseline.remove')}
                    onClick={() =>
                      setItems(items.filter((i) => i.ref !== item.ref))
                    }
                  >
                    <Trash2 />
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
      <div>
        <Button
          size='sm'
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate(
              items.map((i) => ({
                ...i,
                acceptance: i.acceptance.filter((a) => a.trim()),
              }))
            )
          }
        >
          {save.isPending && <Loader2 className='animate-spin' />}
          {t('baseline.save')}
        </Button>
      </div>
    </div>
  )
}

function Clauses({ clauses }: { clauses: string[] }) {
  const { t } = useTranslation('contract')
  if (!clauses.length) return null
  return (
    <ul aria-label={t('baseline.clauses')} className='flex flex-wrap gap-1'>
      {clauses.map((c) => (
        <li
          key={c}
          className='rounded border bg-muted/50 px-1.5 py-0.5 text-xs text-muted-foreground'
        >
          {c}
        </li>
      ))}
    </ul>
  )
}

function ItemList({ items }: { items: BaselineItem[] }) {
  const { t } = useTranslation('contract')
  const format = useFormat()
  return (
    <div className='grid gap-6'>
      {kinds.map((kind) => {
        const group = items.filter((i) => i.kind === kind)
        if (!group.length) return null
        return (
          <div key={kind} className='grid gap-2'>
            <h3 className='text-sm font-semibold'>
              {t(`baseline.kinds.${kind}`)}{' '}
              <span className='font-normal text-muted-foreground'>
                ({group.length})
              </span>
            </h3>
            <ul className='divide-y rounded-lg border bg-card'>
              {group.map((item) => (
                <li
                  key={item.ref}
                  className='grid gap-1 px-3 py-2.5 text-sm sm:grid-cols-[3rem_1fr_auto]'
                >
                  <span className='text-xs text-muted-foreground tabular-nums'>
                    {item.ref}
                  </span>
                  <div className='min-w-0'>
                    <p className='font-medium'>{item.title}</p>
                    {item.description && (
                      <p className='text-muted-foreground'>
                        {item.description}
                      </p>
                    )}
                    {item.acceptance.length > 0 && (
                      <ul className='mt-1 list-disc ps-5 text-muted-foreground'>
                        {item.acceptance.map((a) => (
                          <li key={a}>{a}</li>
                        ))}
                      </ul>
                    )}
                    <div className='mt-1.5'>
                      <Clauses clauses={item.clauses} />
                    </div>
                  </div>
                  {item.price_idr ? (
                    <span
                      className='text-xs text-muted-foreground tabular-nums'
                      title={t('baseline.price')}
                    >
                      {format.rupiah(item.price_idr)}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}
