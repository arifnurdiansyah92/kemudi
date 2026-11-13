import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Check, CircleAlert, Loader2, Plus, Trash2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  emptyRepo,
  hasCheck,
  repoBody,
  useCheckRepo,
  useDeleteRepo,
  useGenerateRepoKey,
  useSaveRepo,
  type Repo,
  type RepoCheck,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { KeyButton, PublicKey } from './public-key'
import { RepoForm } from './repo-form'

type Access = 'ok' | 'failed' | 'unchecked'

function access(r: Repo): Access {
  if (!hasCheck(r.last_check)) return 'unchecked'
  return r.last_check.ok ? 'ok' : 'failed'
}

export function Repos({
  slug,
  repos,
  canEdit,
}: {
  slug: string
  repos: Repo[]
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  // null: closed; 0: a new repo; otherwise the open repo's id.
  const [open, setOpen] = useState<number | null>(null)
  const current = open ? (repos.find((r) => r.id === open) ?? null) : null

  return (
    <div className='grid gap-3'>
      {repos.length === 0 ? (
        <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
          {t('repos.empty')}
        </p>
      ) : (
        <ul className='divide-y rounded-lg border'>
          {repos.map((r) => (
            <li key={r.id}>
              <button
                type='button'
                onClick={() => setOpen(r.id)}
                className='grid w-full gap-1 px-4 py-2.5 text-start hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:gap-4'
              >
                <span className='grid min-w-0 gap-0.5'>
                  <span className='flex flex-wrap items-center gap-2 text-sm font-medium'>
                    {r.name}
                    <Badge variant='secondary' className='font-normal'>
                      {t(`repos.roles.${r.role}`)}
                    </Badge>
                  </span>
                  <span
                    className={cn(
                      'truncate text-xs text-muted-foreground',
                      !r.local && 'font-mono'
                    )}
                  >
                    {r.local ? t('repos.local') : r.url}
                  </span>
                </span>
                <span className='flex items-center gap-4 text-xs text-muted-foreground'>
                  <span className='font-mono'>{r.default_branch}</span>
                  <AccessStatus value={access(r)} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <div>
          <Button size='sm' variant='outline' onClick={() => setOpen(0)}>
            <Plus />
            {t('repos.add')}
          </Button>
        </div>
      )}
      <Sheet open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className='w-full gap-0 overflow-y-auto sm:max-w-xl'>
          {open !== null && (
            <RepoSheetBody
              key={open}
              slug={slug}
              repo={current}
              canEdit={canEdit}
              onCreated={(id) => setOpen(id)}
              onDeleted={() => setOpen(null)}
            />
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function AccessStatus({ value }: { value: Access }) {
  const { t } = useTranslation('agent')
  return (
    <span className='flex items-center gap-1.5 whitespace-nowrap'>
      <span
        aria-hidden
        className={cn(
          'size-2 rounded-full',
          value === 'ok' && 'bg-success',
          value === 'failed' && 'bg-destructive',
          value === 'unchecked' && 'border border-muted-foreground/60'
        )}
      />
      {t(`repos.access.${value}`)}
    </span>
  )
}

function RepoSheetBody({
  slug,
  repo,
  canEdit,
  onCreated,
  onDeleted,
}: {
  slug: string
  repo: Repo | null
  canEdit: boolean
  onCreated: (id: number) => void
  onDeleted: () => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const save = useSaveRepo(slug)
  const remove = useDeleteRepo(slug)
  const genKey = useGenerateRepoKey(slug)
  const check = useCheckRepo(slug)
  const [confirmDelete, setConfirmDelete] = useState(false)
  // The fresh result, until the list refetch brings last_check.
  const [result, setResult] = useState<RepoCheck | null>(null)
  const lastCheck =
    result ?? (repo && hasCheck(repo.last_check) ? repo.last_check : null)

  return (
    <>
      <SheetHeader className='border-b px-6 py-4'>
        <SheetTitle>
          {repo
            ? t('repos.editTitle', { name: repo.name })
            : t('repos.newTitle')}
        </SheetTitle>
        <SheetDescription>{t('repos.description')}</SheetDescription>
      </SheetHeader>
      <div className='grid gap-6 px-6 py-5'>
        <RepoForm
          values={repo ? repoBody(repo) : emptyRepo}
          isNew={!repo}
          canEdit={canEdit}
          pending={save.isPending}
          onSubmit={(values) =>
            save.mutate(
              { ...values, id: repo?.id },
              {
                onSuccess: (saved) => {
                  toast.success(repo ? t('repos.saved') : t('repos.created'))
                  if (!repo) onCreated(saved.id)
                },
              }
            )
          }
        />

        {repo && (
          <section className='grid gap-3 border-t pt-5'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <h3 className='text-sm font-semibold'>
                {t('repos.deployKey.title')}
              </h3>
              {canEdit && !repo.local && (
                <KeyButton
                  hasKey={repo.has_key}
                  pending={genKey.isPending}
                  disabled={check.isPending}
                  onGenerate={() =>
                    genKey.mutate(repo.id, {
                      onSuccess: () => toast.success(t('key.generated')),
                    })
                  }
                />
              )}
            </div>
            {repo.local ? (
              <p className='text-sm text-muted-foreground'>
                {t('repos.deployKey.localHint')}
              </p>
            ) : repo.has_key ? (
              <>
                <PublicKey id={`repo-key-${repo.id}`} value={repo} />
                <p className='text-xs text-muted-foreground'>
                  {t('repos.deployKey.hint')}
                </p>
              </>
            ) : (
              <p className='text-sm text-muted-foreground'>
                {t('repos.deployKey.none')}
              </p>
            )}
          </section>
        )}

        {repo && (
          <section className='grid gap-3 border-t pt-5'>
            <div className='flex flex-wrap items-center justify-between gap-2'>
              <h3 className='text-sm font-semibold'>
                {t('repos.checkAccess.title')}
              </h3>
              {canEdit && (
                <Button
                  size='sm'
                  variant='outline'
                  disabled={
                    check.isPending ||
                    genKey.isPending ||
                    (!repo.local && !repo.has_key)
                  }
                  onClick={() =>
                    check.mutate(repo.id, { onSuccess: setResult })
                  }
                >
                  {check.isPending && <Loader2 className='animate-spin' />}
                  {check.isPending
                    ? t('repos.checkAccess.running')
                    : t('repos.checkAccess.run')}
                </Button>
              )}
            </div>
            <p className='text-xs text-muted-foreground'>
              {!repo.local && !repo.has_key
                ? t('repos.checkAccess.needsKey')
                : t('repos.checkAccess.hint', { branch: repo.default_branch })}
            </p>
            {lastCheck && (
              <CheckResult result={lastCheck} branch={repo.default_branch} />
            )}
          </section>
        )}

        {repo && canEdit && (
          <div className='border-t pt-5'>
            <Button
              variant='ghost'
              size='sm'
              className='text-destructive hover:text-destructive'
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 />
              {t('common:actions.remove')}
            </Button>
            <ConfirmDialog
              open={confirmDelete}
              onOpenChange={setConfirmDelete}
              title={t('repos.deleteTitle', { name: repo.name })}
              desc={t('repos.deleteBody')}
              confirmText={t('common:actions.remove')}
              destructive
              isLoading={remove.isPending}
              handleConfirm={() =>
                remove.mutate(repo.id, {
                  onSuccess: () => {
                    toast.success(t('repos.deleted'))
                    setConfirmDelete(false)
                    onDeleted()
                  },
                  onError: () => setConfirmDelete(false),
                })
              }
            />
          </div>
        )}
      </div>
    </>
  )
}

function CheckResult({
  result,
  branch,
}: {
  result: RepoCheck
  branch: string
}) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const rows = [
    ['clone', t('repos.checkAccess.clone'), result.clone],
    ['push', t('repos.checkAccess.push'), result.push],
    [
      'branch',
      t('repos.checkAccess.branch', { branch }),
      result.default_branch_found,
    ],
  ] as const
  const detected = Object.entries(result.detected ?? {})
    .filter(([, v]) => v)
    .map(([k]) => t(`repos.form.${k}` as 'repos.form.install_cmd'))

  return (
    <div className='grid gap-3'>
      <ul className='divide-y rounded-lg border text-sm'>
        {rows.map(([key, label, ok]) => (
          <li
            key={key}
            className='flex items-center justify-between gap-3 px-3 py-2'
          >
            <span>{label}</span>
            <span
              className={cn(
                'flex items-center gap-1.5 text-xs font-medium',
                ok ? 'text-success' : 'text-destructive'
              )}
            >
              {ok ? <Check className='size-3.5' /> : <X className='size-3.5' />}
              {ok ? t('repos.checkAccess.yes') : t('repos.checkAccess.no')}
            </span>
          </li>
        ))}
      </ul>
      {result.error && (
        <Alert variant='destructive'>
          <CircleAlert />
          <AlertDescription className='font-mono text-xs break-all'>
            {result.error}
          </AlertDescription>
        </Alert>
      )}
      {result.host_key && (
        <p className='text-xs text-muted-foreground'>
          {t('machine.hostKey.label')}{' '}
          <span className='font-mono break-all'>{result.host_key}</span>
        </p>
      )}
      {detected.length > 0 && (
        <p className='text-xs text-muted-foreground'>
          {t('repos.checkAccess.detected', { fields: detected.join(', ') })}
        </p>
      )}
      {result.checked_at && (
        <p className='text-xs text-muted-foreground'>
          {t('machine.check.checkedAt', {
            when: f.date(result.checked_at, 'dateTime'),
          })}
        </p>
      )}
    </div>
  )
}
