import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { CheckCircle2, CircleAlert, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  agentError,
  useLlmLevel,
  useSaveLlmLevel,
  useTestLlmLevel,
  type LlmEffective,
  type LlmIn,
  type LlmLevel,
  type LlmSource,
  type LlmTest,
} from '@/lib/kemudi-ai/agent'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ConfirmDialog } from '@/components/confirm-dialog'

/** "From this agent" / "From project" / "Kemudi server default". */
export function LlmSourceBadge({ source }: { source: LlmSource }) {
  const { t } = useTranslation('agent')
  return (
    <Badge variant='outline' className='font-normal'>
      {t(`llm.source.${source}`)}
    </Badge>
  )
}

/** The badge, then model and host: what a run would use right now. */
function InUse({ effective }: { effective: LlmEffective }) {
  const { t } = useTranslation('agent')
  return (
    <p className='flex flex-wrap items-center gap-x-2 gap-y-1 text-sm'>
      <span className='text-muted-foreground'>{t('llm.inUse')}</span>
      <LlmSourceBadge source={effective.llm_source} />
      <span className='font-mono text-xs'>{effective.llm_model}</span>
      <span className='text-xs text-muted-foreground'>
        {effective.llm_host || t('llm.noHost')}
      </span>
    </p>
  )
}

/** Examples, not prose: the same in every language. */
const URL_EXAMPLE = 'https://api.openai.com/v1'
const MODEL_EXAMPLE = 'gpt-4o-mini'

type Handlers = {
  /** Rejects with the server's error; the form shows it inline. */
  onSave: (body: LlmIn) => Promise<unknown>
  onClear: () => Promise<unknown>
  onTest: (body: LlmIn | null) => Promise<LlmTest>
}

/**
 * Base URL, model and a write-only key. A stored key shows only as its last
 * four characters; a typed key lives in this form until a save succeeds,
 * then it is dropped. An empty key field keeps the stored key.
 */
export function LlmConnectionForm({
  id,
  level,
  canEdit,
  clearBody,
  onSave,
  onClear,
  onTest,
}: {
  /** Prefix for field ids, unique on the page. */
  id: string
  level: LlmLevel
  canEdit: boolean
  /** What clearing means at this level. */
  clearBody: string
} & Handlers) {
  const { t } = useTranslation(['agent', 'common'])
  const [baseUrl, setBaseUrl] = useState(level.base_url)
  const [model, setModel] = useState(level.model)
  const [key, setKey] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [busy, setBusy] = useState<'save' | 'test' | 'clear' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LlmTest | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  const url = baseUrl.trim()
  const name = model.trim()
  const typedKey = key.trim()
  const dirty =
    url !== level.base_url || name !== level.model || typedKey !== ''
  const filled = url !== '' && name !== ''
  const showKeyInput = !level.key_set || replacing
  // A kept key follows the level to a new address; say so before saving.
  const keyMoves =
    level.key_set && !typedKey && level.base_url !== '' && url !== level.base_url
  const off = !canEdit || busy !== null

  const body = (): LlmIn => ({
    base_url: url,
    model: name,
    // Empty means "keep the stored key": never send it as a new one.
    ...(typedKey ? { api_key: typedKey } : {}),
  })

  async function run(kind: 'save' | 'clear', action: () => Promise<unknown>) {
    setBusy(kind)
    setError(null)
    try {
      await action()
      setKey('')
      setReplacing(false)
      setResult(null)
      if (kind === 'clear') {
        setBaseUrl('')
        setModel('')
      }
    } catch (e) {
      setError(agentError(e))
    } finally {
      setBusy(null)
    }
  }

  async function test() {
    setBusy('test')
    setError(null)
    setResult(null)
    try {
      setResult(await onTest(filled ? body() : null))
    } catch (e) {
      setError(agentError(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <form
      className='grid gap-4'
      onSubmit={(e) => {
        e.preventDefault()
        if (dirty && filled && !off) void run('save', () => onSave(body()))
      }}
    >
      <div className='grid items-start gap-4 sm:grid-cols-2'>
        <div className='grid gap-1.5 sm:col-span-2'>
          <Label htmlFor={`${id}-url`}>{t('llm.baseUrl')}</Label>
          <Input
            id={`${id}-url`}
            value={baseUrl}
            inputMode='url'
            spellCheck={false}
            autoComplete='off'
            maxLength={500}
            placeholder={URL_EXAMPLE}
            disabled={!canEdit}
            aria-describedby={`${id}-url-hint`}
            onChange={(e) => setBaseUrl(e.target.value)}
            className='font-mono text-xs'
          />
          <p id={`${id}-url-hint`} className='text-xs text-muted-foreground'>
            {t('llm.baseUrlHint')}
          </p>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-model`}>{t('llm.model')}</Label>
          <Input
            id={`${id}-model`}
            value={model}
            spellCheck={false}
            autoComplete='off'
            maxLength={100}
            placeholder={MODEL_EXAMPLE}
            disabled={!canEdit}
            aria-describedby={`${id}-model-hint`}
            onChange={(e) => setModel(e.target.value)}
            className='font-mono text-xs'
          />
          <p id={`${id}-model-hint`} className='text-xs text-muted-foreground'>
            {t('llm.modelHint')}
          </p>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-key`}>{t('llm.key')}</Label>
          {showKeyInput ? (
            <Input
              id={`${id}-key`}
              type='password'
              value={key}
              spellCheck={false}
              autoComplete='new-password'
              maxLength={1000}
              disabled={!canEdit}
              aria-describedby={`${id}-key-hint`}
              onChange={(e) => setKey(e.target.value)}
              className='font-mono text-xs'
            />
          ) : (
            <div className='flex h-9 items-center justify-between gap-2 rounded-md border border-input bg-muted/50 ps-3 pe-1'>
              <span
                id={`${id}-key`}
                className='font-mono text-xs'
                aria-label={t('llm.keyStored', { last4: level.key_last4 })}
              >
                {`•••• ${level.key_last4 ?? ''}`}
              </span>
              <Button
                type='button'
                size='sm'
                variant='ghost'
                className='h-7'
                disabled={off}
                onClick={() => setReplacing(true)}
              >
                {t('llm.keyReplace')}
              </Button>
            </div>
          )}
          <p id={`${id}-key-hint`} className='text-xs text-muted-foreground'>
            {!level.key_set
              ? t('llm.keyHintNew')
              : replacing
                ? t('llm.keyHintReplace')
                : t('llm.keyHintStored')}
            {replacing && (
              <>
                {' '}
                <button
                  type='button'
                  className='font-medium text-foreground underline underline-offset-4'
                  onClick={() => {
                    setKey('')
                    setReplacing(false)
                  }}
                >
                  {t('llm.keyKeep')}
                </button>
              </>
            )}
          </p>
        </div>
      </div>

      {keyMoves && (
        <p className='text-xs text-muted-foreground'>
          {t('llm.keyMoves', { last4: level.key_last4 })}
        </p>
      )}

      <div className='flex flex-wrap items-center gap-2'>
        <Button type='submit' size='sm' disabled={off || !dirty || !filled}>
          {busy === 'save' && <Loader2 className='animate-spin' />}
          {t('common:actions.save')}
        </Button>
        <Button
          type='button'
          size='sm'
          variant='outline'
          disabled={off}
          onClick={() => void test()}
        >
          {busy === 'test' && <Loader2 className='animate-spin' />}
          {busy === 'test' ? t('llm.testing') : t('llm.test')}
        </Button>
        {level.set && (
          <Button
            type='button'
            size='sm'
            variant='ghost'
            className='ms-auto text-destructive hover:text-destructive'
            disabled={off}
            onClick={() => setConfirmClear(true)}
          >
            {busy === 'clear' && <Loader2 className='animate-spin' />}
            {t('llm.clear')}
          </Button>
        )}
      </div>

      {error && (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      )}
      <TestResult result={result} />

      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title={t('llm.clearConfirm.title')}
        desc={clearBody}
        confirmText={t('llm.clearConfirm.action')}
        destructive
        handleConfirm={() => {
          setConfirmClear(false)
          void run('clear', onClear)
        }}
      />
    </form>
  )
}

function TestResult({ result }: { result: LlmTest | null }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const target = result
    ? t('llm.testTarget', {
        model: result.llm_model,
        host: result.llm_host || t('llm.noHost'),
      })
    : ''
  return (
    <div role='status' aria-live='polite'>
      {result?.ok && (
        <p className='flex flex-wrap items-center gap-x-2 gap-y-1 text-sm'>
          <CheckCircle2 className='size-4 shrink-0 text-success' />
          <span className='font-medium text-success'>
            {t('llm.testOk', { ms: f.number(result.latency_ms) })}
          </span>
          <span className='font-mono text-xs text-muted-foreground'>
            {target}
          </span>
        </p>
      )}
      {result && !result.ok && (
        <Alert variant='destructive'>
          <CircleAlert />
          <AlertDescription className='grid gap-1'>
            <span className='font-medium'>
              {t('llm.testFailed')}{' '}
              <span className='font-mono text-xs font-normal'>{target}</span>
            </span>
            <span className='font-mono text-xs break-all'>
              {result.error ?? `HTTP ${result.status ?? ''}`}
            </span>
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}

function LastChange({ level }: { level: LlmLevel }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  if (!level.updated_by || !level.updated_at) return null
  return (
    <p className='text-xs text-muted-foreground'>
      {t('lastChange', {
        who: level.updated_by,
        when: f.date(level.updated_at, 'dateTime'),
      })}
    </p>
  )
}

function serverDefault(level: LlmLevel, t: (k: 'llm.noHost') => string) {
  return {
    model: level.server_default.model,
    host: level.server_default.host || t('llm.noHost'),
  }
}

/** Project level: "Model connection (all agents)". */
export function ProjectLlm({
  level,
  canEdit,
  ...handlers
}: { level: LlmLevel; canEdit: boolean } & Handlers) {
  const { t } = useTranslation('agent')
  return (
    <div className='grid gap-4'>
      <div className='grid gap-1'>
        <InUse effective={level.effective} />
        <p className='text-xs text-muted-foreground'>
          {t('llm.hierarchy', serverDefault(level, t))}
        </p>
      </div>
      <LlmConnectionForm
        id='llm-project'
        level={level}
        canEdit={canEdit}
        clearBody={t('llm.clearConfirm.projectBody')}
        {...handlers}
      />
      <LastChange level={level} />
    </div>
  )
}

/**
 * Agent level. "Use project default" on means this role has no connection of
 * its own; turning it back on after one was saved clears it.
 */
export function RoleLlm({
  roleId,
  level,
  canEdit,
  ...handlers
}: { roleId: number; level: LlmLevel; canEdit: boolean } & Handlers) {
  const { t } = useTranslation('agent')
  const [custom, setCustom] = useState(level.set)
  const [confirm, setConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function clear() {
    setClearing(true)
    setError(null)
    try {
      await handlers.onClear()
      setCustom(false)
    } catch (e) {
      setError(agentError(e))
    } finally {
      setClearing(false)
    }
  }

  return (
    <div className='grid gap-4'>
      <div className='flex flex-wrap items-center gap-3'>
        <Switch
          id={`llm-role-${roleId}-default`}
          checked={!custom}
          disabled={!canEdit || clearing}
          onCheckedChange={(useDefault) => {
            if (!useDefault) setCustom(true)
            else if (level.set) setConfirm(true)
            else setCustom(false)
          }}
        />
        <Label htmlFor={`llm-role-${roleId}-default`}>
          {t('llm.useDefault')}
        </Label>
        {clearing && (
          <Loader2 className='size-3.5 animate-spin text-muted-foreground' />
        )}
      </div>
      <div className='grid gap-1'>
        <InUse effective={level.effective} />
        <p className='text-xs text-muted-foreground'>
          {t('llm.roleHierarchy', serverDefault(level, t))}
        </p>
      </div>
      {error && (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      )}
      {custom && (
        <LlmConnectionForm
          id={`llm-role-${roleId}`}
          level={level}
          canEdit={canEdit}
          clearBody={t('llm.clearConfirm.roleBody')}
          {...handlers}
          onClear={async () => {
            await handlers.onClear()
            setCustom(false)
          }}
        />
      )}
      {level.set && <LastChange level={level} />}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t('llm.clearConfirm.title')}
        desc={t('llm.clearConfirm.roleBody')}
        confirmText={t('llm.clearConfirm.action')}
        destructive
        handleConfirm={() => {
          setConfirm(false)
          void clear()
        }}
      />
    </div>
  )
}

/** Wires a level to the API. `roleId` null is the project level. */
function useLlmHandlers(slug: string, roleId: number | null): Handlers {
  const { t } = useTranslation('agent')
  const save = useSaveLlmLevel(slug, roleId)
  const test = useTestLlmLevel(slug, roleId)
  return {
    onSave: (body) =>
      save
        .mutateAsync(body)
        .then(() => toast.success(t('llm.saved'))),
    onClear: () =>
      save
        .mutateAsync({ base_url: '', model: '', clear: true })
        .then(() => toast.success(t('llm.cleared'))),
    onTest: (body) => test.mutateAsync(body),
  }
}

export function ProjectLlmSection({
  slug,
  canEdit,
}: {
  slug: string
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const level = useLlmLevel(slug, null)
  const handlers = useLlmHandlers(slug, null)
  if (level.isPending) return <Skeleton className='h-48 w-full' />
  if (level.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('llm.unavailable')}
      </p>
    )
  return (
    <ProjectLlm
      // A save or clear comes back with a new time: start the form afresh.
      key={level.data.updated_at ?? 'never'}
      level={level.data}
      canEdit={canEdit}
      {...handlers}
    />
  )
}

export function RoleLlmSection({
  slug,
  roleId,
  canEdit,
}: {
  slug: string
  roleId: number
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const level = useLlmLevel(slug, roleId)
  const handlers = useLlmHandlers(slug, roleId)
  if (level.isPending) return <Skeleton className='h-24 w-full' />
  if (level.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('llm.unavailable')}
      </p>
    )
  return (
    <RoleLlm
      key={level.data.updated_at ?? 'never'}
      roleId={roleId}
      level={level.data}
      canEdit={canEdit}
      {...handlers}
    />
  )
}
