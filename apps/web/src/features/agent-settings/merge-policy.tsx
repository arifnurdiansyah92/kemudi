import { useState } from 'react'
import * as RadioGroupPrimitive from '@radix-ui/react-radio-group'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  mergeModes,
  qaModes,
  type Executor,
  type MergeMode,
  type QaMode,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ConfirmDialog } from '@/components/confirm-dialog'

/**
 * Segmented Off / Gates only / Browser, with every mode's one line under it
 * so they can be compared without saving. Lowering QA below Browser is
 * locked while merge is Auto (the server refuses it too).
 */
export function QaModeControl({
  value,
  mergeMode,
  canEdit,
  pending,
  error,
  onChange,
}: {
  value: QaMode
  mergeMode: MergeMode
  canEdit: boolean
  pending?: boolean
  /** The server's refusal of the last change, e.g. Browser without a runbook. */
  error?: string | null
  onChange: (mode: QaMode) => void
}) {
  const { t } = useTranslation('agent')
  const lockedByAuto = mergeMode === 'auto' && value === 'browser'

  return (
    <div className='grid gap-2.5'>
      <div className='flex items-center gap-2'>
        <span id='qa-mode-label' className='text-sm font-medium'>
          {t('merge.qa.label')}
        </span>
        {pending && (
          <Loader2 className='size-3.5 animate-spin text-muted-foreground' />
        )}
      </div>
      <RadioGroupPrimitive.Root
        value={value}
        disabled={!canEdit || pending}
        aria-labelledby='qa-mode-label'
        aria-describedby='qa-mode-help'
        orientation='horizontal'
        onValueChange={(v) => {
          if (v !== value) onChange(v as QaMode)
        }}
        className='grid grid-cols-3 gap-0.5 rounded-lg bg-muted p-0.5 sm:inline-grid sm:w-fit'
      >
        {qaModes.map((mode) => (
          <RadioGroupPrimitive.Item
            key={mode}
            value={mode}
            disabled={lockedByAuto && mode !== 'browser'}
            className={cn(
              'rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors outline-none',
              'hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50',
              'data-[state=checked]:bg-background data-[state=checked]:text-foreground data-[state=checked]:shadow-xs',
              'disabled:cursor-not-allowed disabled:hover:text-muted-foreground',
              'data-[state=unchecked]:disabled:opacity-50'
            )}
          >
            {t(`merge.qa.modes.${mode}.label`)}
          </RadioGroupPrimitive.Item>
        ))}
      </RadioGroupPrimitive.Root>
      <dl id='qa-mode-help' className='grid gap-1 text-sm'>
        {qaModes.map((mode) => (
          <div
            key={mode}
            className={cn(
              'grid gap-x-3 sm:grid-cols-[7.5rem_minmax(0,1fr)]',
              mode === value ? 'text-foreground' : 'text-muted-foreground'
            )}
          >
            <dt className={cn(mode === value && 'font-medium')}>
              {t(`merge.qa.modes.${mode}.label`)}
            </dt>
            <dd>{t(`merge.qa.modes.${mode}.help`)}</dd>
          </div>
        ))}
      </dl>
      {lockedByAuto && canEdit && (
        <p className='text-xs text-muted-foreground'>
          {t('merge.qa.lockedByAuto')}
        </p>
      )}
      {error && (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Three radio cards, each with the risk it carries. `auto` asks first: it
 * merges and deploys with nobody looking, so it also needs Browser QA.
 */
export function MergePolicy({
  value,
  qaMode,
  branch,
  canEdit,
  pending,
  onChange,
}: {
  value: MergeMode
  qaMode: QaMode
  /** The default branch name(s) to name in the copy. */
  branch: string
  canEdit: boolean
  pending?: boolean
  onChange: (mode: MergeMode) => void
}) {
  const { t } = useTranslation('agent')
  const [confirmAuto, setConfirmAuto] = useState(false)
  // Already Auto (set before QA modes existed) stays selectable.
  const autoLocked = qaMode !== 'browser' && value !== 'auto'

  return (
    <div className='grid gap-2.5'>
      <span id='merge-mode-label' className='text-sm font-medium'>
        {t('merge.label', { branch })}
      </span>
      <RadioGroup
        value={value}
        disabled={!canEdit || pending}
        aria-labelledby='merge-mode-label'
        onValueChange={(v) => {
          const mode = v as MergeMode
          if (mode === value) return
          if (mode === 'auto') setConfirmAuto(true)
          else onChange(mode)
        }}
        className='gap-2'
      >
        {mergeModes.map((mode) => {
          const locked = mode === 'auto' && autoLocked
          return (
            <label
              key={mode}
              htmlFor={`merge-${mode}`}
              className={cn(
                'flex cursor-pointer items-start gap-3 rounded-lg border px-4 py-3 transition-colors hover:bg-accent/40',
                'has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent/40',
                'has-[:disabled]:cursor-default has-[:disabled]:hover:bg-transparent',
                locked && 'border-dashed'
              )}
            >
              <RadioGroupItem
                id={`merge-${mode}`}
                value={mode}
                disabled={locked}
                aria-describedby={locked ? 'merge-auto-locked' : undefined}
                className='mt-0.5'
              />
              <span className='grid gap-0.5'>
                <span className='flex flex-wrap items-center gap-2 text-sm font-medium'>
                  {t(`merge.modes.${mode}.label`)}
                  {mode === 'approve' && (
                    <Badge variant='outline' className='font-normal'>
                      {t('merge.default')}
                    </Badge>
                  )}
                  {pending && mode === value && (
                    <Loader2 className='size-3.5 animate-spin text-muted-foreground' />
                  )}
                </span>
                <span className='text-sm text-muted-foreground'>
                  {t(`merge.modes.${mode}.risk`, { branch })}
                </span>
                {locked && (
                  <span
                    id='merge-auto-locked'
                    className='mt-1 text-xs font-medium text-foreground'
                  >
                    {t('merge.modes.auto.needsBrowser')}
                  </span>
                )}
              </span>
            </label>
          )
        })}
      </RadioGroup>
      <ConfirmDialog
        open={confirmAuto}
        onOpenChange={setConfirmAuto}
        title={t('merge.confirm.title')}
        desc={t('merge.confirm.body', { branch })}
        confirmText={t('merge.confirm.action')}
        destructive
        handleConfirm={() => {
          setConfirmAuto(false)
          onChange('auto')
        }}
      />
    </div>
  )
}

/** A command, not prose: the same in every language. */
const DEPLOY_EXAMPLE = 'docker compose up -d --build'

/** The post-merge deploy command; the hint says where it runs. */
export function DeployCommand({
  value,
  isSet,
  executor,
  host,
  user,
  canEdit,
  pending,
  onSave,
}: {
  /** `null` when the reader is not an admin: the command may hold a token. */
  value: string | null
  isSet: boolean
  executor: Executor
  host: string
  user: string
  canEdit: boolean
  pending?: boolean
  onSave: (command: string) => void
}) {
  const { t } = useTranslation(['agent', 'common'])
  const [text, setText] = useState(value ?? '')
  const hint =
    executor === 'ssh'
      ? t('merge.deploy.hintSsh', { host, user })
      : t('merge.deploy.hintLocal')
  if (value === null || !canEdit)
    return (
      <div className='grid gap-1.5'>
        <p className='text-sm font-medium'>{t('merge.deploy.label')}</p>
        <p className='text-sm'>
          {isSet ? t('merge.deploy.set') : t('merge.deploy.notSet')}
        </p>
        <p className='text-xs text-muted-foreground'>{hint}</p>
      </div>
    )
  const dirty = text !== value
  return (
    <form
      className='grid gap-1.5'
      onSubmit={(e) => {
        e.preventDefault()
        onSave(text)
      }}
    >
      <label htmlFor='deploy-command' className='text-sm font-medium'>
        {t('merge.deploy.label')}
      </label>
      <textarea
        id='deploy-command'
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        spellCheck={false}
        maxLength={2000}
        aria-describedby='deploy-command-hint'
        placeholder={DEPLOY_EXAMPLE}
        className='w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50'
      />
      <p id='deploy-command-hint' className='text-xs text-muted-foreground'>
        {hint}
      </p>
      <div className='flex gap-2'>
        <Button type='submit' size='sm' disabled={!dirty || pending}>
          {pending && <Loader2 className='animate-spin' />}
          {t('common:actions.save')}
        </Button>
        {dirty && (
          <Button
            type='button'
            size='sm'
            variant='ghost'
            onClick={() => setText(value)}
          >
            {t('common:actions.cancel')}
          </Button>
        )}
      </div>
    </form>
  )
}
