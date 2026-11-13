import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  mergeModes,
  type Executor,
  type MergeMode,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { ConfirmDialog } from '@/components/confirm-dialog'

/**
 * Three radio cards, each with the risk it carries. `auto` asks first: it
 * merges and deploys with nobody looking.
 */
export function MergePolicy({
  value,
  branch,
  canEdit,
  pending,
  onChange,
}: {
  value: MergeMode
  /** The default branch name(s) to name in the copy. */
  branch: string
  canEdit: boolean
  pending?: boolean
  onChange: (mode: MergeMode) => void
}) {
  const { t } = useTranslation('agent')
  const [confirmAuto, setConfirmAuto] = useState(false)

  return (
    <>
      <RadioGroup
        value={value}
        disabled={!canEdit || pending}
        aria-label={t('merge.title')}
        onValueChange={(v) => {
          const mode = v as MergeMode
          if (mode === value) return
          if (mode === 'auto') setConfirmAuto(true)
          else onChange(mode)
        }}
        className='gap-2'
      >
        {mergeModes.map((mode) => (
          <label
            key={mode}
            htmlFor={`merge-${mode}`}
            className={cn(
              'flex cursor-pointer items-start gap-3 rounded-lg border px-4 py-3 transition-colors hover:bg-accent/40',
              'has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent/40',
              'has-[:disabled]:cursor-default has-[:disabled]:hover:bg-transparent'
            )}
          >
            <RadioGroupItem
              id={`merge-${mode}`}
              value={mode}
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
            </span>
          </label>
        ))}
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
    </>
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
