import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import {
  CircleAlert,
  Loader2,
  Lock,
  Pencil,
  Plus,
  ShieldAlert,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  agentError,
  ENV_NAME_RE,
  useDeleteEnvVar,
  useEnvVars,
  useSaveEnvVar,
  type EnvVar,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ConfirmDialog } from '@/components/confirm-dialog'

/** What the dialog edits: a stored value, a runbook name without one, or new. */
type Editing = { var: EnvVar | null }

/** Project settings → Agent → Env & secrets. Members read names and plain
 * values; admins add, edit and delete. A secret is write-only. */
export function EnvVarsCard({
  slug,
  canEdit,
}: {
  slug: string
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const query = useEnvVars(slug)
  const [editing, setEditing] = useState<Editing | null>(null)

  if (query.isPending) return <Skeleton className='h-24 w-full' />
  if (query.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('env.unavailable')}
      </p>
    )

  const vars = query.data
  const missing = vars.filter((v) => v.required && !v.set).length

  return (
    <div className='grid gap-3'>
      <Alert>
        <ShieldAlert />
        <AlertDescription>{t('env.testOnly')}</AlertDescription>
      </Alert>

      {missing > 0 && (
        <p className='flex items-center gap-1.5 text-sm text-destructive'>
          <CircleAlert className='size-4 shrink-0' aria-hidden />
          {t('env.missing', { count: missing })}
        </p>
      )}

      {vars.length === 0 ? (
        <p className='rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground'>
          {t('env.empty')}
        </p>
      ) : (
        <ul className='divide-y rounded-lg border text-sm'>
          {vars.map((v) => (
            <EnvRow
              key={v.name}
              v={v}
              canEdit={canEdit}
              onEdit={() => setEditing({ var: v })}
            />
          ))}
        </ul>
      )}

      {canEdit && (
        <div>
          <Button
            size='sm'
            variant='outline'
            onClick={() => setEditing({ var: null })}
          >
            <Plus />
            {t('env.add')}
          </Button>
        </div>
      )}

      {canEdit && (
        <Dialog
          open={editing !== null}
          onOpenChange={(open) => !open && setEditing(null)}
        >
          <DialogContent className='sm:max-w-lg'>
            {editing !== null && (
              <EnvDialogBody
                key={editing.var?.name ?? ''}
                slug={slug}
                current={editing.var}
                onDone={() => setEditing(null)}
              />
            )}
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}

function EnvRow({
  v,
  canEdit,
  onEdit,
}: {
  v: EnvVar
  canEdit: boolean
  onEdit: () => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const f = useFormat()
  return (
    <li className='grid gap-x-4 gap-y-1 px-3 py-2.5 sm:grid-cols-[minmax(0,17rem)_minmax(0,1fr)_auto] sm:items-center'>
      <span className='grid min-w-0 gap-0.5'>
        <span className='flex flex-wrap items-center gap-x-2 gap-y-0.5'>
          <code className='font-mono text-xs font-medium break-all'>
            {v.name}
          </code>
          {[
            v.secret && t('env.secret'),
            v.required && t('env.required'),
            v.in_runbook && t('env.fromRunbook'),
          ]
            .filter(Boolean)
            .map((flag) => (
              <span
                key={flag as string}
                className='text-xs text-muted-foreground'
              >
                {flag}
              </span>
            ))}
        </span>
        {v.description && (
          <span className='text-xs text-muted-foreground'>{v.description}</span>
        )}
      </span>
      <span className='grid min-w-0 gap-0.5'>
        <EnvValue v={v} />
        {v.set && v.updated_by && v.updated_at && (
          <span className='text-xs text-muted-foreground'>
            {t('env.updated', {
              who: v.updated_by,
              when: f.date(v.updated_at, 'dateTime'),
            })}
          </span>
        )}
      </span>
      {canEdit && (
        <Button
          size='sm'
          variant='ghost'
          className='justify-self-start sm:justify-self-end'
          aria-label={
            v.set
              ? t('env.edit', { name: v.name })
              : t('env.setValue', { name: v.name })
          }
          onClick={onEdit}
        >
          {v.set ? <Pencil /> : <Plus />}
          <span aria-hidden>
            {v.set ? t('common:actions.edit') : t('env.setShort')}
          </span>
        </Button>
      )}
    </li>
  )
}

function EnvValue({ v }: { v: EnvVar }) {
  const { t } = useTranslation('agent')
  if (!v.set)
    return (
      <span
        className={cn(
          'text-xs',
          v.required ? 'font-medium text-destructive' : 'text-muted-foreground'
        )}
      >
        {v.required ? t('env.missingRequired') : t('env.notSet')}
      </span>
    )
  if (v.secret)
    return (
      <span className='flex items-center gap-1.5 text-xs text-muted-foreground'>
        <Lock className='size-3.5' aria-hidden />
        {t('env.hidden')}
      </span>
    )
  if (!v.value)
    return (
      <span className='text-xs text-muted-foreground'>
        {t('env.emptyValue')}
      </span>
    )
  return <code className='font-mono text-xs break-all'>{v.value}</code>
}

function EnvDialogBody({
  slug,
  current,
  onDone,
}: {
  slug: string
  current: EnvVar | null
  onDone: () => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const save = useSaveEnvVar(slug)
  const remove = useDeleteEnvVar(slug)
  const stored = current?.set ?? false
  const [name, setName] = useState(current?.name ?? '')
  const [secret, setSecret] = useState(current?.secret ?? true)
  const [value, setValue] = useState(
    stored && current && !current.secret ? (current.value ?? '') : ''
  )
  const [problem, setProblem] = useState<'name' | 'value' | 'retype' | null>(
    null
  )
  const [serverError, setServerError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  // A stored secret is kept when the field is left empty, unless it would
  // stop being secret (its old value would then be shown).
  const keepsStored = stored && current?.secret === true && secret
  const valueHint = keepsStored
    ? t('env.dialog.valueStored')
    : secret
      ? t('env.dialog.valueHidden')
      : t('env.dialog.valuePlain')

  const submit = () => {
    setServerError(null)
    if (!ENV_NAME_RE.test(name)) return setProblem('name')
    let sent: string | null = value
    if (value === '') {
      if (keepsStored) sent = null
      else if (stored && current?.secret && !secret) return setProblem('retype')
      else if (!stored || secret) return setProblem('value')
    }
    setProblem(null)
    save.mutate(
      { name, value: sent, secret },
      {
        onSuccess: () => {
          toast.success(t('env.saved', { name }))
          onDone()
        },
        onError: (error) => setServerError(agentError(error)),
      }
    )
  }

  const valueError =
    problem === 'value'
      ? t('env.dialog.valueRequired')
      : problem === 'retype'
        ? t('env.dialog.valueRetype')
        : null

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {current
            ? t('env.dialog.editTitle', { name: current.name })
            : t('env.dialog.newTitle')}
        </DialogTitle>
        <DialogDescription>{t('env.dialog.description')}</DialogDescription>
      </DialogHeader>
      <form
        id='env-var-form'
        className='grid gap-4'
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div className='grid gap-1.5'>
          <Label htmlFor='env-name'>{t('env.dialog.name')}</Label>
          <Input
            id='env-name'
            value={name}
            disabled={current !== null}
            maxLength={64}
            spellCheck={false}
            autoCapitalize='characters'
            autoComplete='off'
            aria-invalid={problem === 'name' || undefined}
            aria-describedby={current === null ? 'env-name-hint' : undefined}
            onChange={(e) => setName(e.target.value.toUpperCase())}
            // fixed once stored: shown as text, not a dimmed control
            className='font-mono text-xs disabled:bg-muted/50 disabled:opacity-100'
          />
          {current === null && (
            <p
              id='env-name-hint'
              className={cn(
                'text-xs',
                problem === 'name'
                  ? 'text-destructive'
                  : 'text-muted-foreground'
              )}
            >
              {problem === 'name'
                ? t('env.dialog.nameInvalid')
                : t('env.dialog.nameHint')}
            </p>
          )}
        </div>

        <div className='grid gap-1.5'>
          <Label htmlFor='env-value'>{t('env.dialog.value')}</Label>
          <Input
            id='env-value'
            type={secret ? 'password' : 'text'}
            value={value}
            maxLength={8192}
            spellCheck={false}
            autoComplete={secret ? 'new-password' : 'off'}
            placeholder={keepsStored ? '••••••••' : undefined}
            aria-invalid={valueError !== null || undefined}
            aria-describedby='env-value-hint'
            onChange={(e) => setValue(e.target.value)}
            className='font-mono text-xs'
          />
          <p
            id='env-value-hint'
            className={cn(
              'text-xs',
              valueError ? 'text-destructive' : 'text-muted-foreground'
            )}
          >
            {valueError ?? valueHint}
          </p>
        </div>

        <div className='flex items-start gap-3'>
          <Switch
            id='env-secret'
            checked={secret}
            onCheckedChange={(on) => {
              setSecret(on)
              setProblem(null)
            }}
            aria-describedby='env-secret-hint'
          />
          <div className='grid gap-0.5'>
            <Label htmlFor='env-secret'>{t('env.dialog.secret')}</Label>
            <p id='env-secret-hint' className='text-xs text-muted-foreground'>
              {t('env.dialog.secretHint')}
            </p>
          </div>
        </div>

        {serverError && (
          <p role='alert' className='text-sm text-destructive'>
            {serverError}
          </p>
        )}
      </form>
      <DialogFooter className='sm:justify-between'>
        {stored && current ? (
          <Button
            type='button'
            variant='ghost'
            className='text-destructive hover:text-destructive'
            onClick={() => setConfirming(true)}
          >
            {t('env.dialog.delete')}
          </Button>
        ) : (
          <span className='hidden sm:block' />
        )}
        <div className='flex flex-col-reverse gap-2 sm:flex-row'>
          <Button type='button' variant='ghost' onClick={onDone}>
            {t('common:actions.cancel')}
          </Button>
          <Button type='submit' form='env-var-form' disabled={save.isPending}>
            {save.isPending && <Loader2 className='animate-spin' />}
            {t('env.dialog.save')}
          </Button>
        </div>
      </DialogFooter>
      {current && (
        <ConfirmDialog
          open={confirming}
          onOpenChange={setConfirming}
          destructive
          title={t('env.confirmDelete.title', { name: current.name })}
          desc={t('env.confirmDelete.desc', { name: current.name })}
          confirmText={t('env.confirmDelete.confirm')}
          isLoading={remove.isPending}
          handleConfirm={() =>
            remove.mutate(current.name, {
              onSuccess: () => {
                toast.success(t('env.deleted', { name: current.name }))
                setConfirming(false)
                onDone()
              },
            })
          }
        />
      )}
    </>
  )
}
