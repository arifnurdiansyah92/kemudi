import { useEffect, useMemo, useState } from 'react'
import { Check, ChevronsUpDown, Loader2, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  agentError,
  useLlmModels,
  type LlmModelsIn,
  type LlmSource,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { providerOf, PROVIDERS, selectClass } from './providers'

const URL_EXAMPLE = 'https://api.openai.com/v1'
const MODEL_RE = /^[A-Za-z0-9._:/-]{1,100}$/

/**
 * Provider preset and base URL, as two grid cells. Picking a preset fills the
 * URL; editing the URL to anything else makes it Custom.
 */
export function ProviderFields({
  id,
  url,
  onUrl,
  disabled,
}: {
  id: string
  url: string
  onUrl: (url: string) => void
  disabled: boolean
}) {
  const { t } = useTranslation('agent')
  const [custom, setCustom] = useState(false)
  const preset = providerOf(url)
  const value = preset ?? (custom || url.trim() ? 'custom' : '')
  return (
    <>
      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-provider`}>{t('llm.provider')}</Label>
        <select
          id={`${id}-provider`}
          value={value}
          disabled={disabled}
          onChange={(e) => {
            const p = PROVIDERS.find((x) => x.id === e.target.value)
            if (p) {
              setCustom(false)
              onUrl(p.url)
            } else {
              setCustom(true)
              if (preset) onUrl('')
            }
          }}
          className={selectClass}
        >
          {value === '' && (
            <option value='' disabled>
              {t('llm.providerPick')}
            </option>
          )}
          {PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
          <option value='custom'>{t('llm.providerCustom')}</option>
        </select>
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor={`${id}-url`}>{t('llm.baseUrl')}</Label>
        <Input
          id={`${id}-url`}
          value={url}
          inputMode='url'
          spellCheck={false}
          autoComplete='off'
          maxLength={500}
          placeholder={URL_EXAMPLE}
          disabled={disabled}
          aria-describedby={`${id}-url-hint`}
          onChange={(e) => onUrl(e.target.value)}
          className='font-mono text-xs'
        />
        <p id={`${id}-url-hint`} className='text-xs text-muted-foreground'>
          {preset === 'ollama' ? t('llm.ollamaHint') : t('llm.baseUrlHint')}
        </p>
      </div>
    </>
  )
}

/** Write-only key: a stored key shows only as its last four characters. */
export function KeyField({
  id,
  keySet,
  last4,
  value,
  onChange,
  replacing,
  onReplacing,
  disabled,
}: {
  id: string
  keySet: boolean
  last4: string | null
  value: string
  onChange: (key: string) => void
  replacing: boolean
  onReplacing: (replacing: boolean) => void
  disabled: boolean
}) {
  const { t } = useTranslation('agent')
  const showInput = !keySet || replacing
  return (
    <div className='grid gap-1.5'>
      <Label htmlFor={`${id}-key`}>{t('llm.key')}</Label>
      {showInput ? (
        <Input
          id={`${id}-key`}
          type='password'
          value={value}
          spellCheck={false}
          autoComplete='new-password'
          maxLength={1000}
          disabled={disabled}
          aria-describedby={`${id}-key-hint`}
          onChange={(e) => onChange(e.target.value)}
          className='font-mono text-xs'
        />
      ) : (
        <div className='flex h-9 items-center justify-between gap-2 rounded-md border border-input bg-muted/50 ps-3 pe-1'>
          <span
            id={`${id}-key`}
            className='font-mono text-xs'
            aria-label={t('llm.keyStored', { last4 })}
          >
            {`•••• ${last4 ?? ''}`}
          </span>
          <Button
            type='button'
            size='sm'
            variant='ghost'
            className='h-7'
            disabled={disabled}
            onClick={() => onReplacing(true)}
          >
            {t('llm.keyReplace')}
          </Button>
        </div>
      )}
      <p id={`${id}-key-hint`} className='text-xs text-muted-foreground'>
        {!keySet
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
                onChange('')
                onReplacing(false)
              }}
            >
              {t('llm.keyKeep')}
            </button>
          </>
        )}
      </p>
    </div>
  )
}

/** The request settles for half a second before it is sent. */
function useSettled(body: LlmModelsIn): LlmModelsIn {
  const json = JSON.stringify(body)
  const [settled, setSettled] = useState(json)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(json), 500)
    return () => clearTimeout(timer)
  }, [json])
  return useMemo(() => JSON.parse(settled) as LlmModelsIn, [settled])
}

const MAX_SHOWN = 200

/**
 * The model, picked from the provider's own list (fetched the first time the
 * list opens, or on Refresh) or typed freely. `inherit` adds an empty choice
 * that means "the connection's model".
 */
export function ModelPicker({
  id,
  slug,
  request,
  canFetch,
  value,
  onChange,
  disabled,
  inherit,
  fallback,
  hint,
}: {
  id: string
  slug: string
  /** Which connection to list models for. */
  request: LlmModelsIn
  /** Listing is admin only. */
  canFetch: boolean
  value: string
  onChange: (model: string) => void
  disabled: boolean
  inherit?: { model: string } | null
  /** Where the list comes from before it has loaded. */
  fallback: { source: LlmSource; host: string }
  hint?: string
}) {
  const { t } = useTranslation('agent')
  const [open, setOpen] = useState(false)
  const [armed, setArmed] = useState(false)
  const [search, setSearch] = useState('')
  const settled = useSettled(request)
  const q = useLlmModels(slug, settled, canFetch && armed)

  const models = useMemo(() => q.data?.models ?? [], [q.data])
  const s = search.trim()
  const shown = useMemo(() => {
    const needle = s.toLowerCase()
    return models
      .filter((m) => !needle || m.toLowerCase().includes(needle))
      .slice(0, MAX_SHOWN)
  }, [models, s])
  const freeText = s && MODEL_RE.test(s) && !models.includes(s) ? s : ''

  const source = q.data?.source ?? fallback.source
  const host = q.data?.host || fallback.host || t('llm.noHost')
  const failed = q.error
    ? agentError(q.error)
    : q.data && !q.data.ok
      ? (q.data.error ?? '')
      : null

  function pick(model: string) {
    onChange(model)
    setOpen(false)
  }

  return (
    <div className='grid gap-1.5'>
      <Label htmlFor={id}>{t('llm.model')}</Label>
      <div className='flex gap-2'>
        <Popover
          open={open}
          onOpenChange={(o) => {
            setOpen(o)
            if (o) {
              setArmed(true)
              setSearch('')
            }
          }}
        >
          <PopoverTrigger asChild>
            <Button
              id={id}
              type='button'
              variant='outline'
              role='combobox'
              aria-expanded={open}
              aria-describedby={`${id}-source`}
              disabled={disabled}
              className='h-9 min-w-0 flex-1 justify-between px-3 font-normal'
            >
              <span
                className={cn(
                  'truncate',
                  value ? 'font-mono text-xs' : 'text-muted-foreground'
                )}
              >
                {value ||
                  (inherit
                    ? t('llm.models.inherit', { model: inherit.model })
                    : t('llm.models.placeholder'))}
              </span>
              <ChevronsUpDown className='opacity-50' />
            </Button>
          </PopoverTrigger>
          <PopoverContent
            align='start'
            className='w-(--radix-popover-trigger-width) min-w-72 p-0'
          >
            <Command shouldFilter={false}>
              <CommandInput
                value={search}
                onValueChange={setSearch}
                placeholder={t('llm.models.search')}
              />
              <CommandList>
                {(inherit && !s) || freeText ? (
                  <CommandGroup>
                    {inherit && !s && (
                      <CommandItem value='__inherit' onSelect={() => pick('')}>
                        <Check className={cn(value && 'opacity-0')} />
                        {t('llm.models.inherit', { model: inherit.model })}
                      </CommandItem>
                    )}
                    {freeText && (
                      <CommandItem
                        value={`__use:${freeText}`}
                        onSelect={() => pick(freeText)}
                      >
                        <Check className='opacity-0' />
                        {t('llm.models.use', { model: freeText })}
                      </CommandItem>
                    )}
                  </CommandGroup>
                ) : null}
                {shown.length > 0 && (
                  <CommandGroup>
                    {shown.map((m) => (
                      <CommandItem
                        key={m}
                        value={m}
                        onSelect={() => pick(m)}
                        className='font-mono text-xs'
                      >
                        <Check className={cn(m !== value && 'opacity-0')} />
                        <span className='truncate'>{m}</span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
                {q.isFetching && models.length === 0 ? (
                  <p className='flex items-center gap-2 px-3 py-4 text-sm text-muted-foreground'>
                    <Loader2 className='size-4 animate-spin' />
                    {t('llm.models.loading')}
                  </p>
                ) : shown.length === 0 && !freeText ? (
                  <p className='px-3 py-4 text-sm text-muted-foreground'>
                    {failed !== null
                      ? t('llm.models.failedShort')
                      : t('llm.models.empty')}
                  </p>
                ) : null}
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
        <Button
          type='button'
          size='icon'
          variant='outline'
          className='size-9 shrink-0'
          disabled={!canFetch || q.isFetching}
          aria-label={t('llm.models.refresh')}
          title={t('llm.models.refresh')}
          onClick={() => {
            if (armed) void q.refetch()
            else setArmed(true)
          }}
        >
          <RefreshCw className={cn(q.isFetching && 'animate-spin')} />
        </Button>
      </div>
      <p id={`${id}-source`} className='text-xs text-muted-foreground'>
        {[
          t(`llm.source.${source}`),
          host,
          ...(q.data?.ok
            ? [t('llm.models.count', { count: models.length })]
            : []),
        ].join(' · ')}
      </p>
      {failed !== null && (
        <p role='alert' className='text-xs break-all text-destructive'>
          {t('llm.models.failed', { error: failed })}
        </p>
      )}
      {hint && <p className='text-xs text-muted-foreground'>{hint}</p>}
    </div>
  )
}
