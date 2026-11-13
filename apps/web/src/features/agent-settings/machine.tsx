import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { CircleAlert, Info, Loader2 } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import {
  hasPreflight,
  type AgentSettings,
  type AgentSettingsIn,
  type Executor,
  type Preflight,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { KeyButton, PublicKey } from './public-key'

type Pending = { save: boolean; key: boolean; check: boolean; forget: boolean }

export function Machine({
  settings,
  canEdit,
  pending,
  onSave,
  onGenerateKey,
  onCheck,
  onForgetHostKey,
}: {
  settings: AgentSettings
  canEdit: boolean
  pending: Pending
  onSave: (
    patch: Pick<
      AgentSettingsIn,
      'executor' | 'ssh_host' | 'ssh_port' | 'ssh_user'
    >
  ) => void
  onGenerateKey: () => void
  onCheck: () => void
  onForgetHostKey: () => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const [executor, setExecutor] = useState<Executor>(settings.executor)
  const [host, setHost] = useState(settings.ssh_host)
  const [port, setPort] = useState(String(settings.ssh_port))
  const [user, setUser] = useState(settings.ssh_user)
  const [forget, setForget] = useState(false)

  const portNumber = Number(port)
  const dirty =
    executor !== settings.executor ||
    (executor === 'ssh' &&
      (host !== settings.ssh_host ||
        portNumber !== settings.ssh_port ||
        user !== settings.ssh_user))
  const valid =
    executor === 'local' ||
    (host.trim() !== '' &&
      user.trim() !== '' &&
      Number.isInteger(portNumber) &&
      portNumber >= 1 &&
      portNumber <= 65535)
  // The saved machine is what the check and the key belong to.
  const savedSsh = settings.executor === 'ssh'
  const preflight = hasPreflight(settings.preflight) ? settings.preflight : null
  const hasKey = !!settings.ssh_public_key
  const busy = Object.values(pending).some(Boolean)

  return (
    <div className='grid gap-5'>
      <div className='grid gap-2'>
        <Label id='machine-kind'>{t('machine.label')}</Label>
        <Tabs
          value={executor}
          onValueChange={(v) => setExecutor(v as Executor)}
        >
          <TabsList aria-labelledby='machine-kind'>
            <TabsTrigger value='local' disabled={!canEdit}>
              {t('machine.local')}
            </TabsTrigger>
            <TabsTrigger value='ssh' disabled={!canEdit}>
              {t('machine.ssh')}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        {executor === 'local' && (
          <p className='text-sm text-muted-foreground'>
            {t('machine.localHint')}
          </p>
        )}
      </div>

      {executor === 'ssh' && (
        <>
          <Alert>
            <Info />
            <AlertTitle>{t('machine.remoteNotice.title')}</AlertTitle>
            <AlertDescription>
              {t('machine.remoteNotice.body')}
            </AlertDescription>
          </Alert>
          <div className='grid gap-3 sm:grid-cols-[minmax(0,1fr)_6rem_minmax(0,12rem)]'>
            <div className='grid gap-1.5'>
              <Label htmlFor='ssh-host'>{t('machine.host')}</Label>
              <Input
                id='ssh-host'
                value={host}
                readOnly={!canEdit}
                autoComplete='off'
                spellCheck={false}
                onChange={(e) => setHost(e.target.value.trim())}
              />
            </div>
            <div className='grid gap-1.5'>
              <Label htmlFor='ssh-port'>{t('machine.port')}</Label>
              <Input
                id='ssh-port'
                inputMode='numeric'
                value={port}
                readOnly={!canEdit}
                onChange={(e) => setPort(e.target.value.replace(/\D/g, ''))}
              />
            </div>
            <div className='grid gap-1.5'>
              <Label htmlFor='ssh-user'>{t('machine.user')}</Label>
              <Input
                id='ssh-user'
                value={user}
                readOnly={!canEdit}
                autoComplete='off'
                spellCheck={false}
                onChange={(e) => setUser(e.target.value.trim())}
              />
            </div>
          </div>
        </>
      )}

      {canEdit && dirty && (
        <div className='flex gap-2'>
          <Button
            size='sm'
            disabled={!valid || pending.save}
            onClick={() =>
              onSave({
                executor,
                ssh_host: executor === 'ssh' ? host : settings.ssh_host,
                ssh_port: executor === 'ssh' ? portNumber : settings.ssh_port,
                ssh_user: executor === 'ssh' ? user : settings.ssh_user,
              })
            }
          >
            {pending.save && <Loader2 className='animate-spin' />}
            {t('machine.save')}
          </Button>
          <Button
            size='sm'
            variant='ghost'
            onClick={() => {
              setExecutor(settings.executor)
              setHost(settings.ssh_host)
              setPort(String(settings.ssh_port))
              setUser(settings.ssh_user)
            }}
          >
            {t('common:actions.cancel')}
          </Button>
        </div>
      )}

      {executor === 'ssh' && savedSsh && !dirty && (
        <div className='grid gap-3 border-t pt-4'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <h3 className='text-sm font-medium'>{t('machine.key.title')}</h3>
            {canEdit && (
              <KeyButton
                hasKey={hasKey}
                pending={pending.key}
                disabled={busy}
                onGenerate={onGenerateKey}
              />
            )}
          </div>
          {hasKey ? (
            <>
              <PublicKey
                id='machine-public-key'
                value={{
                  public_key: settings.ssh_public_key,
                  fingerprint: settings.ssh_fingerprint,
                }}
              />
              <p className='text-xs text-muted-foreground'>
                <Trans
                  t={t}
                  i18nKey='machine.key.hint'
                  values={{ file: '~/.ssh/authorized_keys' }}
                  components={{ code: <code /> }}
                />
              </p>
            </>
          ) : (
            <p className='text-sm text-muted-foreground'>
              {t('machine.key.none')}
            </p>
          )}
        </div>
      )}

      {!dirty && (executor === 'local' || savedSsh) && (
        <div className='grid gap-3 border-t pt-4'>
          <div className='flex flex-wrap items-center justify-between gap-2'>
            <PreflightSummary result={preflight} />
            {canEdit && (
              <Button
                size='sm'
                variant='outline'
                disabled={busy || (executor === 'ssh' && !hasKey)}
                title={
                  executor === 'ssh' && !hasKey
                    ? t('machine.check.needsKey')
                    : undefined
                }
                onClick={onCheck}
              >
                {pending.check && <Loader2 className='animate-spin' />}
                {pending.check
                  ? t('machine.check.running')
                  : t('machine.check.run')}
              </Button>
            )}
          </div>
          {preflight && <PreflightResult result={preflight} />}
          {executor === 'ssh' && preflight?.host_key && (
            <div className='grid gap-1'>
              <div className='flex flex-wrap items-center justify-between gap-2'>
                <p className='text-sm'>
                  <span className='font-medium'>
                    {t('machine.hostKey.label')}
                  </span>{' '}
                  <span className='font-mono text-xs break-all'>
                    {preflight.host_key}
                  </span>
                </p>
                {canEdit && (
                  <Button
                    size='sm'
                    variant='ghost'
                    disabled={busy}
                    onClick={() => setForget(true)}
                  >
                    {t('machine.hostKey.forget')}
                  </Button>
                )}
              </div>
              <p className='text-xs text-muted-foreground'>
                {t('machine.hostKey.hint')}
              </p>
            </div>
          )}
        </div>
      )}
      <ConfirmDialog
        open={forget}
        onOpenChange={setForget}
        title={t('machine.hostKey.confirmTitle')}
        desc={t('machine.hostKey.confirmBody', { host: settings.ssh_host })}
        confirmText={t('machine.hostKey.forget')}
        destructive
        handleConfirm={() => {
          setForget(false)
          onForgetHostKey()
        }}
      />
    </div>
  )
}

function PreflightSummary({ result }: { result: Preflight | null }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  if (!result)
    return (
      <p className='text-sm text-muted-foreground'>
        {t('machine.check.never')}
      </p>
    )
  return (
    <div className='grid gap-0.5'>
      <p
        className={cn(
          'flex items-center gap-2 text-sm font-medium',
          !result.ok && 'text-destructive'
        )}
      >
        <span
          aria-hidden
          className={cn(
            'size-2 rounded-full',
            result.ok ? 'bg-success' : 'bg-destructive'
          )}
        />
        {result.ok
          ? t('machine.check.passed', { count: result.slots })
          : t('machine.check.failed')}
      </p>
      <p className='text-xs text-muted-foreground'>
        {t('machine.check.checkedAt', {
          when: f.date(result.checked_at, 'dateTime'),
        })}
      </p>
    </div>
  )
}

/** The probe's facts against the per-job minimum, then the problems. */
export function PreflightResult({ result }: { result: Preflight }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const min = result.minimum
  const gb = (v: number | null) =>
    v === null
      ? t('machine.check.unknown')
      : t('machine.check.gbValue', { value: f.number(v) })
  const rows: { key: string; found: string; minimum: string; ok: boolean }[] = [
    {
      key: 'cpu',
      found:
        result.cpu === null
          ? t('machine.check.unknown')
          : t('machine.check.cpuValue', { count: result.cpu }),
      minimum: t('machine.check.cpuValue', { count: min.cpu }),
      ok: result.cpu !== null && result.cpu >= min.cpu,
    },
    {
      key: 'ram',
      found: gb(result.ram_gb),
      minimum: gb(min.ram_gb),
      ok: result.ram_gb !== null && result.ram_gb >= min.ram_gb,
    },
    {
      key: 'disk',
      found: gb(result.disk_gb),
      minimum: gb(min.disk_gb),
      ok: result.disk_gb !== null && result.disk_gb >= min.disk_gb,
    },
    {
      key: 'docker',
      found: result.docker ?? t('machine.check.notFound'),
      minimum: t('machine.check.required'),
      ok: !!result.docker,
    },
    {
      key: 'arch',
      found: result.arch ?? t('machine.check.unknown'),
      minimum: '—',
      ok: true,
    },
  ]
  return (
    <div className='grid gap-3'>
      {result.error && (
        <Alert variant='destructive'>
          <CircleAlert />
          <AlertDescription className='font-mono text-xs break-all'>
            {result.error}
          </AlertDescription>
        </Alert>
      )}
      <div className='overflow-x-auto rounded-lg border'>
        <table className='w-full text-sm'>
          <thead className='bg-muted/50 text-xs text-muted-foreground'>
            <tr>
              <th className='px-3 py-2 text-start font-medium'>
                {t('machine.check.fact')}
              </th>
              <th className='px-3 py-2 text-start font-medium'>
                {t('machine.check.found')}
              </th>
              <th className='px-3 py-2 text-start font-medium'>
                {t('machine.check.minimum')}
              </th>
            </tr>
          </thead>
          <tbody className='divide-y'>
            {rows.map((r) => (
              <tr key={r.key}>
                <th scope='row' className='px-3 py-2 text-start font-normal'>
                  {t(`machine.check.${r.key}` as 'machine.check.cpu')}
                </th>
                <td
                  className={cn(
                    'px-3 py-2 tabular-nums',
                    !r.ok && 'text-destructive'
                  )}
                >
                  {r.found}
                </td>
                <td className='px-3 py-2 text-muted-foreground tabular-nums'>
                  {r.minimum}
                </td>
              </tr>
            ))}
            <tr>
              <th scope='row' className='px-3 py-2 text-start font-medium'>
                {t('machine.check.slots')}
              </th>
              <td
                className={cn(
                  'px-3 py-2 font-medium tabular-nums',
                  result.slots === 0 && 'text-destructive'
                )}
              >
                {result.slots}
              </td>
              <td className='px-3 py-2 text-muted-foreground tabular-nums'>
                1
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {result.problems.length > 0 && (
        <div className='grid gap-1'>
          <p className='text-sm font-medium'>{t('machine.check.problems')}</p>
          <ul className='grid gap-1 text-sm text-destructive'>
            {result.problems.map((p) => (
              <li key={p} className='flex gap-2'>
                <CircleAlert className='mt-0.5 size-3.5 shrink-0' />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
