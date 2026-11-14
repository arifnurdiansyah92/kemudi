import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  agentError,
  OVERLAY_MAX,
  roleAreas,
  roleTemplates,
  type LlmIn,
  type LlmLevel,
  type LlmTest,
  type Repo,
  type Role,
  type RoleArea,
  type RoleIn,
  type RolePrompt,
  type RoleTemplate,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  InsecureHttpNotice,
  KeyField,
  ModelPicker,
  ProviderFields,
} from './connection-fields'
import { TestResult } from './llm-connection'
import { hostOf } from './providers'
import { useInsecureHttp } from './use-insecure-http'

const lines = (text: string) =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)

/** What happens to the role's own connection on save: set it (the model is
 * the role's model) or clear it. An empty `api_key` keeps the stored key. */
export type ConnChange =
  | { clear: true }
  | {
      clear?: false
      base_url: string
      api_key?: string
      allow_insecure_http?: boolean
    }

function blankRole(): RoleIn {
  return {
    name: '',
    template: 'frontend',
    area: 'web',
    model: '',
    repo_ids: [],
    allowed_paths: [],
    denied_paths: [],
    prompt_overlay: '',
    enabled: true,
  }
}

const fieldClass =
  'h-9 rounded-md border border-input bg-background px-2 text-sm shadow-xs disabled:opacity-60'
const textareaClass =
  'w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive read-only:bg-muted/50'

/**
 * A role's settings and prompt. The Kemudi rules and the role template are
 * shown read-only above the one part an admin writes: the overlay.
 */
export function RoleEditor({
  slug,
  role,
  level,
  projectLevel,
  prompt,
  promptPending,
  repos,
  canEdit,
  pending,
  onSave,
  onTest,
}: {
  slug: string
  role: Role | null
  /** This role's own connection; null for a role not saved yet. */
  level: LlmLevel | null
  /** The project level, whose `effective` is what this role inherits. */
  projectLevel: LlmLevel | undefined
  prompt: RolePrompt | undefined
  promptPending?: boolean
  repos: Repo[]
  canEdit: boolean
  pending: boolean
  onSave: (role: RoleIn, conn: ConnChange | null) => void
  /** Tests unsaved values against this role's connection. */
  onTest?: (body: LlmIn) => Promise<LlmTest>
}) {
  const { t } = useTranslation(['agent', 'common'])
  const f = useFormat()
  const initial: RoleIn = role ?? blankRole()
  const [name, setName] = useState(initial.name)
  const [template, setTemplate] = useState<RoleTemplate>(initial.template)
  const [area, setArea] = useState<RoleArea>(initial.area)
  // One model field: the role's own model, or (for an older role with its own
  // connection and no model of its own) that connection's model.
  const [model, setModel] = useState(
    initial.model || (level?.set ? level.model : '')
  )
  const [repoIds, setRepoIds] = useState<number[]>(initial.repo_ids)
  const [allowed, setAllowed] = useState(initial.allowed_paths.join('\n'))
  const [denied, setDenied] = useState(initial.denied_paths.join('\n'))
  const [overlay, setOverlay] = useState(initial.prompt_overlay)
  const [enabled, setEnabled] = useState(initial.enabled)

  // The connection: the project's (inherited) or this agent's own.
  const [custom, setCustom] = useState(level?.set ?? false)
  const [baseUrl, setBaseUrl] = useState(level?.base_url ?? '')
  const [key, setKey] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<LlmTest | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  const over = overlay.length - OVERLAY_MAX
  const ro = !canEdit
  const url = baseUrl.trim()
  const typedKey = key.trim()
  const savedLevel = level?.set ?? false
  const inherited = projectLevel?.effective
  const insecure = useInsecureHttp(url, {
    url: level?.base_url ?? '',
    insecure: level?.insecure_http ?? false,
  })
  const valid =
    name.trim() !== '' &&
    over <= 0 &&
    (!custom || (url !== '' && model.trim() !== '' && !insecure.blocked))

  function connChange(): ConnChange | null {
    if (!custom) return savedLevel ? { clear: true } : null
    const same =
      savedLevel &&
      url === level?.base_url &&
      model.trim() === level.model &&
      !typedKey
    if (same) return null
    return {
      base_url: url,
      ...(typedKey ? { api_key: typedKey } : {}),
      ...insecure.flag,
    }
  }

  async function test() {
    if (!onTest) return
    setTesting(true)
    setResult(null)
    setTestError(null)
    try {
      setResult(
        await onTest({
          base_url: url,
          model: model.trim(),
          ...(typedKey ? { api_key: typedKey } : {}),
          ...insecure.flag,
        })
      )
    } catch (e) {
      const message = agentError(e)
      insecure.noteError(message)
      setTestError(message)
    } finally {
      setTesting(false)
    }
  }

  return (
    <form
      className='grid gap-5'
      onSubmit={(e) => {
        e.preventDefault()
        if (!valid) return
        onSave(
          {
            name: name.trim(),
            template,
            area,
            model: model.trim(),
            repo_ids: repoIds,
            allowed_paths: lines(allowed),
            denied_paths: lines(denied),
            prompt_overlay: overlay,
            enabled,
          },
          connChange()
        )
      }}
    >
      <div className='grid items-start gap-4 sm:grid-cols-2'>
        <div className='grid gap-1.5 sm:col-span-2'>
          <Label htmlFor='role-name'>{t('roles.editor.name')}</Label>
          <Input
            id='role-name'
            value={name}
            maxLength={100}
            readOnly={ro}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='role-template'>{t('roles.editor.template')}</Label>
          <select
            id='role-template'
            value={template}
            disabled={ro}
            onChange={(e) => {
              const next = e.target.value as RoleTemplate
              setTemplate(next)
              // A Fullstack role is for stories touching both sides.
              if (next === 'fullstack') setArea('both')
            }}
            className={fieldClass}
          >
            {roleTemplates.map((x) => (
              <option key={x} value={x}>
                {t(`roles.templates.${x}`)}
              </option>
            ))}
          </select>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='role-area'>{t('roles.editor.area')}</Label>
          <select
            id='role-area'
            value={area}
            disabled={ro}
            onChange={(e) => setArea(e.target.value as RoleArea)}
            aria-describedby='role-area-hint'
            className={fieldClass}
          >
            {roleAreas.map((x) => (
              <option key={x} value={x}>
                {t(`roles.areas.${x}`)}
              </option>
            ))}
          </select>
          <p id='role-area-hint' className='text-xs text-muted-foreground'>
            {area === 'both'
              ? t('roles.editor.areaHintBoth')
              : t('roles.editor.areaHint', { area })}
          </p>
        </div>
      </div>

      <div className='flex items-center gap-3'>
        <Switch
          id='role-enabled'
          checked={enabled}
          disabled={ro}
          onCheckedChange={setEnabled}
        />
        <Label htmlFor='role-enabled'>{t('roles.editor.enabled')}</Label>
      </div>

      <section className='grid gap-4 border-t pt-5'>
        <div className='grid gap-1'>
          <h3 className='text-sm font-medium'>{t('llm.roleTitle')}</h3>
          <p className='text-xs text-muted-foreground'>
            {t('llm.roleDescription')}
          </p>
        </div>
        <div className='flex items-center gap-3'>
          <Switch
            id='role-llm-default'
            checked={!custom}
            disabled={ro}
            onCheckedChange={(useDefault) => {
              setCustom(!useDefault)
              setResult(null)
              setTestError(null)
            }}
          />
          <Label htmlFor='role-llm-default'>{t('llm.useDefault')}</Label>
        </div>
        <div className='grid items-start gap-4 sm:grid-cols-2'>
          {custom && (
            <>
              <ProviderFields
                id='role-llm'
                url={baseUrl}
                onUrl={setBaseUrl}
                disabled={ro}
              />
              <KeyField
                id='role-llm'
                keySet={level?.key_set ?? false}
                last4={level?.key_last4 ?? null}
                value={key}
                onChange={setKey}
                replacing={replacing}
                onReplacing={setReplacing}
                disabled={ro}
              />
              {insecure.shown && (
                <InsecureHttpNotice
                  id='role-llm'
                  checked={insecure.ack}
                  onCheckedChange={insecure.setAck}
                  disabled={ro}
                />
              )}
            </>
          )}
          <ModelPicker
            id='role-model'
            slug={slug}
            request={
              custom
                ? {
                    ...(role ? { role_id: role.id } : {}),
                    base_url: url,
                    ...(typedKey ? { api_key: typedKey } : {}),
                    ...insecure.flag,
                  }
                : {}
            }
            canFetch={
              canEdit && (!custom || (hostOf(url) !== '' && !insecure.blocked))
            }
            value={model}
            onChange={setModel}
            disabled={ro}
            inherit={custom ? null : { model: inherited?.llm_model ?? '' }}
            fallback={
              custom
                ? { source: 'agent', host: hostOf(url) }
                : {
                    source: inherited?.llm_source ?? 'project',
                    host: inherited?.llm_host ?? '',
                  }
            }
            hint={
              custom
                ? model.trim()
                  ? t('llm.modelHint')
                  : t('llm.roleModelRequired')
                : t('roles.editor.modelHint')
            }
          />
        </div>
        {!custom && level && (
          <p className='text-xs text-muted-foreground'>
            {savedLevel
              ? t('llm.roleClears')
              : t('llm.roleHierarchy', {
                  model: level.server_default.model,
                  host: level.server_default.host || t('llm.noHost'),
                })}
          </p>
        )}
        {custom && role && onTest && (
          <div className='grid gap-3'>
            <div>
              <Button
                type='button'
                size='sm'
                variant='outline'
                disabled={ro || testing || !valid}
                onClick={() => void test()}
              >
                {testing && <Loader2 className='animate-spin' />}
                {testing ? t('llm.testing') : t('llm.test')}
              </Button>
            </div>
            {testError && (
              <p role='alert' className='text-sm text-destructive'>
                {testError}
              </p>
            )}
            <TestResult result={result} />
          </div>
        )}
      </section>

      <fieldset className='grid gap-2'>
        <legend className='text-sm font-medium'>
          {t('roles.editor.repos')}
        </legend>
        <p className='text-xs text-muted-foreground'>
          {t('roles.editor.reposHint')}
        </p>
        {repos.length === 0 ? (
          <p className='text-sm text-muted-foreground'>
            {t('roles.editor.noRepos')}
          </p>
        ) : (
          <div className='flex flex-wrap gap-x-5 gap-y-2'>
            {repos.map((r) => (
              <label key={r.id} className='flex items-center gap-2 text-sm'>
                <Checkbox
                  checked={repoIds.includes(r.id)}
                  disabled={ro}
                  onCheckedChange={(c) =>
                    setRepoIds((ids) =>
                      c ? [...ids, r.id] : ids.filter((i) => i !== r.id)
                    )
                  }
                />
                {r.name}
              </label>
            ))}
          </div>
        )}
      </fieldset>

      <div className='grid items-start gap-4 sm:grid-cols-2'>
        <div className='grid gap-1.5'>
          <Label htmlFor='role-allowed'>{t('roles.editor.allowed')}</Label>
          <textarea
            id='role-allowed'
            rows={3}
            value={allowed}
            readOnly={ro}
            spellCheck={false}
            onChange={(e) => setAllowed(e.target.value)}
            className={cn(textareaClass, 'font-mono text-xs')}
          />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='role-denied'>{t('roles.editor.denied')}</Label>
          <textarea
            id='role-denied'
            rows={3}
            value={denied}
            readOnly={ro}
            spellCheck={false}
            onChange={(e) => setDenied(e.target.value)}
            className={cn(textareaClass, 'font-mono text-xs')}
          />
        </div>
        <p className='-mt-2 text-xs text-muted-foreground sm:col-span-2'>
          {t('roles.editor.pathsHint')}
        </p>
      </div>

      <section className='grid gap-3 border-t pt-5'>
        {role === null ? (
          <p className='text-sm text-muted-foreground'>
            {t('roles.editor.fixedAfterSave')}
          </p>
        ) : promptPending || !prompt ? (
          <p className='text-sm text-muted-foreground'>
            {t('roles.editor.loadingPrompt')}
          </p>
        ) : (
          <>
            <FixedBlock
              title={t('roles.editor.fixed')}
              hint={t('roles.editor.fixedHint')}
              text={prompt.fixed}
            />
            <FixedBlock
              title={t('roles.editor.templateFixed')}
              text={prompt.role}
            />
          </>
        )}

        <div className='grid gap-1.5'>
          <Label htmlFor='role-overlay'>{t('roles.editor.overlay')}</Label>
          <p id='role-overlay-hint' className='text-xs text-muted-foreground'>
            {t('roles.editor.overlayHint')}
          </p>
          <textarea
            id='role-overlay'
            rows={8}
            value={overlay}
            readOnly={ro}
            aria-invalid={over > 0}
            aria-describedby='role-overlay-hint role-overlay-count'
            onChange={(e) => setOverlay(e.target.value)}
            className={textareaClass}
          />
          <p
            id='role-overlay-count'
            aria-live='polite'
            className={cn(
              'text-end text-xs tabular-nums',
              over > 0
                ? 'font-medium text-destructive'
                : 'text-muted-foreground'
            )}
          >
            {t('roles.editor.count', {
              used: f.number(overlay.length),
              max: f.number(OVERLAY_MAX),
            })}
            {over > 0 &&
              ` · ${t('roles.editor.tooLong', { over: f.number(over) })}`}
          </p>
        </div>
      </section>

      {canEdit && (
        <div className='flex flex-wrap items-center gap-3'>
          <Button type='submit' disabled={!valid || pending}>
            {pending && <Loader2 className='animate-spin' />}
            {role ? t('common:actions.saveChanges') : t('roles.add')}
          </Button>
          {role && (
            <span className='font-mono text-xs text-muted-foreground'>
              {t('roles.promptVersion', { version: role.prompt_version })}
            </span>
          )}
        </div>
      )}
      {!canEdit && role && (
        <p className='font-mono text-xs text-muted-foreground'>
          {t('roles.promptVersion', { version: role.prompt_version })}
        </p>
      )}
    </form>
  )
}

function FixedBlock({
  title,
  hint,
  text,
}: {
  title: string
  hint?: string
  text: string
}) {
  return (
    <div className='grid gap-1.5'>
      <p className='text-sm font-medium'>{title}</p>
      {hint && <p className='text-xs text-muted-foreground'>{hint}</p>}
      <pre className='max-h-56 overflow-auto rounded-md border bg-muted/50 px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground'>
        {text}
      </pre>
    </div>
  )
}
