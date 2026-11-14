import { type FormEvent, useId, useState } from 'react'
import { useFormat } from '@/i18n/format'
import { CircleAlert, Gauge, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  currencies,
  useAgentUsage,
  useSaveBudget,
  type AgentUsage,
  type BudgetIn,
  type Currency,
} from '@/lib/kemudi-ai/usage'
import { cn } from '@/lib/utils'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

const MILLION = 1_000_000

/** Project settings → Agent → Usage and budget. */
export function UsageBudgetCard({
  slug,
  canEdit,
}: {
  slug: string
  canEdit: boolean
}) {
  const { t } = useTranslation('agent')
  const query = useAgentUsage(slug)
  const save = useSaveBudget(slug)

  if (query.isPending) return <Skeleton className='h-40 w-full' />
  if (query.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('usage.unavailable')}
      </p>
    )
  return (
    <UsageBudget
      // A save answers with the new values: the form starts from them.
      key={JSON.stringify([query.data.budget, query.data.price_override])}
      usage={query.data}
      canEdit={canEdit}
      pending={save.isPending}
      onSave={(body) =>
        save.mutate(body, {
          onSuccess: () => toast.success(t('usage.saved')),
        })
      }
    />
  )
}

export function UsageBudget({
  usage,
  canEdit,
  pending,
  onSave,
}: {
  usage: AgentUsage
  canEdit: boolean
  pending: boolean
  onSave: (body: BudgetIn) => void
}) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const b = usage.budget
  const pct = b.used_ratio == null ? null : Math.round(b.used_ratio * 100)
  const millions = (n: number) =>
    f.number(n / MILLION, { maximumFractionDigits: 1 })

  return (
    <div className='grid gap-6'>
      <BudgetBanner usage={usage} />

      <dl className='grid gap-4 sm:grid-cols-3'>
        <div className='grid gap-1.5'>
          <dt className='text-xs text-muted-foreground'>
            {t('usage.tokensMonth')}
          </dt>
          <dd className='grid gap-2'>
            <span className='text-lg font-semibold tabular-nums'>
              {b.monthly_tokens
                ? t('usage.tokensOf', {
                    used: millions(usage.tokens),
                    budget: millions(b.monthly_tokens),
                  })
                : t('usage.tokensM', { tokens: millions(usage.tokens) })}
            </span>
            {pct != null && (
              <div
                className='h-1.5 overflow-hidden rounded-full bg-muted'
                role='progressbar'
                aria-label={t('usage.progress')}
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className={cn(
                    'h-full',
                    b.exceeded
                      ? 'bg-destructive'
                      : b.warning
                        ? 'bg-primary'
                        : 'bg-success'
                  )}
                  style={{ width: `${Math.min(pct, 100)}%` }}
                />
              </div>
            )}
          </dd>
        </div>
        <div className='grid gap-1.5'>
          <dt className='text-xs text-muted-foreground'>
            {t('usage.costMonth')}
          </dt>
          <dd className='grid gap-0.5'>
            <span className='text-lg font-semibold tabular-nums'>
              {f.rupiah(usage.cost_idr)}
            </span>
            {usage.unknown_cost_calls > 0 && (
              <span className='text-xs text-muted-foreground'>
                {t('usage.unknownCalls', { count: usage.unknown_cost_calls })}
              </span>
            )}
            {usage.unreported_calls > 0 && (
              <span className='text-xs text-muted-foreground'>
                {t('usage.unreportedCalls', {
                  count: usage.unreported_calls,
                })}
              </span>
            )}
          </dd>
        </div>
        <div className='grid gap-1.5'>
          <dt className='text-xs text-muted-foreground'>
            {t('usage.setupMonth')}
          </dt>
          <dd className='text-sm tabular-nums'>
            {t('usage.setupValue', {
              tokens: millions(usage.setup_tokens),
              cost: f.rupiah(usage.setup_cost_idr),
            })}
          </dd>
        </div>
      </dl>

      <PriceLine usage={usage} />

      <RecentStories usage={usage} />

      <BudgetForm
        usage={usage}
        canEdit={canEdit}
        pending={pending}
        onSave={onSave}
      />
    </div>
  )
}

function BudgetBanner({ usage }: { usage: AgentUsage }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const b = usage.budget
  const millions = (n: number) =>
    f.number(n / MILLION, { maximumFractionDigits: 1 })

  if (b.exceeded)
    return (
      <Alert variant='destructive'>
        <CircleAlert />
        <AlertTitle>{t('usage.exceeded.title')}</AlertTitle>
        <AlertDescription>{t('usage.exceeded.body')}</AlertDescription>
      </Alert>
    )
  if (b.warning && b.used_ratio != null)
    return (
      <Alert>
        <Gauge />
        <AlertTitle>
          {t('usage.warning.title', { pct: Math.round(b.used_ratio * 100) })}
        </AlertTitle>
        <AlertDescription>{t('usage.warning.body')}</AlertDescription>
      </Alert>
    )
  if (!b.monthly_tokens)
    return (
      <p className='rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground'>
        {t('usage.recommend', {
          tokens: millions(b.recommended_monthly_tokens),
        })}
      </p>
    )
  return null
}

function PriceLine({ usage }: { usage: AgentUsage }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const p = usage.price
  if (p.input == null || p.output == null || !p.currency)
    return (
      <p className='text-sm text-muted-foreground'>
        {t('usage.price.unknown', { model: p.model })}
      </p>
    )
  const money = (n: number) =>
    p.currency === 'IDR'
      ? f.rupiah(n)
      : t('usage.price.usd', {
          amount: f.number(n, { maximumFractionDigits: 4 }),
        })
  return (
    <p className='text-sm text-muted-foreground'>
      {t('usage.price.known', {
        model: p.model,
        input: money(p.input),
        output: money(p.output),
      })}{' '}
      {p.source === 'project'
        ? t('usage.price.fromProject')
        : p.source === 'flat'
          ? t('usage.price.fromFlat')
          : t('usage.price.fromTable')}
    </p>
  )
}

function RecentStories({ usage }: { usage: AgentUsage }) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const head = 'px-3 py-2 text-start font-medium whitespace-nowrap'

  if (usage.stories.length === 0)
    return (
      <p className='rounded-lg border border-dashed px-4 py-4 text-sm text-muted-foreground'>
        {t('usage.stories.empty')}
      </p>
    )
  return (
    <div className='overflow-x-auto rounded-lg border'>
      <table className='w-full text-sm'>
        <caption className='sr-only'>{t('usage.stories.caption')}</caption>
        <thead className='bg-muted/50 text-xs text-muted-foreground'>
          <tr>
            <th className={head}>{t('jobs.story')}</th>
            <th className={cn(head, 'text-end')}>
              {t('usage.stories.tokens')}
            </th>
            <th className={cn(head, 'text-end')}>{t('usage.stories.cost')}</th>
            <th className={cn(head, 'text-end')}>{t('usage.stories.calls')}</th>
          </tr>
        </thead>
        <tbody className='divide-y'>
          {usage.stories.map((s) => {
            const over =
              usage.budget.story_cap != null &&
              s.tokens >= usage.budget.story_cap
            return (
              <tr key={s.job_id}>
                <td className='px-3 py-2 font-medium tabular-nums'>
                  #{s.story_ref}
                </td>
                <td
                  className={cn(
                    'px-3 py-2 text-end tabular-nums',
                    over && 'text-destructive'
                  )}
                >
                  {f.number(s.tokens)}
                </td>
                <td className='px-3 py-2 text-end whitespace-nowrap tabular-nums'>
                  {s.cost_unknown
                    ? s.cost_idr > 0
                      ? t('usage.stories.atLeast', {
                          cost: f.rupiah(s.cost_idr),
                        })
                      : t('usage.stories.unknown')
                    : f.rupiah(s.cost_idr)}
                </td>
                <td className='px-3 py-2 text-end tabular-nums'>{s.calls}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Millions of tokens as typed ('' = unlimited); null when not a number. */
function parseMillions(v: string): number | null | undefined {
  const s = v.trim().replace(',', '.')
  if (!s) return null
  const n = Number(s)
  if (!Number.isFinite(n) || n < 0) return undefined
  return Math.round(n * MILLION)
}

function parsePrice(v: string): number | null | undefined {
  const s = v.trim().replace(',', '.')
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) && n >= 0 ? n : undefined
}

const asMillions = (n: number | null) => (n ? String(n / MILLION) : '')
const asText = (n: number | null | undefined) => (n == null ? '' : String(n))

function BudgetForm({
  usage,
  canEdit,
  pending,
  onSave,
}: {
  usage: AgentUsage
  canEdit: boolean
  pending: boolean
  onSave: (body: BudgetIn) => void
}) {
  const { t } = useTranslation('agent')
  const id = useId()
  const o = usage.price_override
  const [monthly, setMonthly] = useState(
    asMillions(usage.budget.monthly_tokens)
  )
  const [cap, setCap] = useState(asMillions(usage.budget.story_cap))
  const [override, setOverride] = useState(o != null)
  const [input, setInput] = useState(asText(o?.input))
  const [cached, setCached] = useState(asText(o?.cached_input))
  const [output, setOutput] = useState(asText(o?.output))
  const [currency, setCurrency] = useState<Currency>(o?.currency ?? 'USD')
  const [error, setError] = useState<string | null>(null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const m = parseMillions(monthly)
    const c = parseMillions(cap)
    if (m === undefined || c === undefined) {
      setError(t('usage.form.badNumber'))
      return
    }
    let price: BudgetIn['price'] = null
    if (override) {
      const i = parsePrice(input)
      const ci = parsePrice(cached)
      const out = parsePrice(output)
      if (i == null || out == null || ci === undefined) {
        setError(t('usage.form.badPrice'))
        return
      }
      price = { input: i, cached_input: ci, output: out, currency }
    }
    setError(null)
    onSave({ monthly_tokens: m, story_cap: c, price })
  }

  return (
    <form className='grid gap-4' onSubmit={submit} noValidate>
      <div className='grid gap-4 sm:grid-cols-2'>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-monthly`}>{t('usage.form.monthly')}</Label>
          <Input
            id={`${id}-monthly`}
            inputMode='decimal'
            value={monthly}
            disabled={!canEdit || pending}
            placeholder={t('usage.form.unlimited')}
            onChange={(e) => setMonthly(e.target.value)}
          />
          <p className='text-xs text-muted-foreground'>
            {t('usage.form.monthlyHint')}
          </p>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor={`${id}-cap`}>{t('usage.form.cap')}</Label>
          <Input
            id={`${id}-cap`}
            inputMode='decimal'
            value={cap}
            disabled={!canEdit || pending}
            placeholder={t('usage.form.unlimited')}
            onChange={(e) => setCap(e.target.value)}
          />
          <p className='text-xs text-muted-foreground'>
            {t('usage.form.capHint')}
          </p>
        </div>
      </div>

      <div className='flex items-center gap-3'>
        <Switch
          id={`${id}-override`}
          checked={override}
          disabled={!canEdit || pending}
          onCheckedChange={setOverride}
        />
        <Label htmlFor={`${id}-override`}>{t('usage.form.override')}</Label>
      </div>
      {override && (
        <div className='grid gap-4 sm:grid-cols-4'>
          <div className='grid gap-1.5'>
            <Label htmlFor={`${id}-input`}>{t('usage.form.input')}</Label>
            <Input
              id={`${id}-input`}
              inputMode='decimal'
              value={input}
              disabled={!canEdit || pending}
              onChange={(e) => setInput(e.target.value)}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor={`${id}-cached`}>{t('usage.form.cached')}</Label>
            <Input
              id={`${id}-cached`}
              inputMode='decimal'
              value={cached}
              disabled={!canEdit || pending}
              placeholder={t('usage.form.cachedPlaceholder')}
              onChange={(e) => setCached(e.target.value)}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor={`${id}-output`}>{t('usage.form.output')}</Label>
            <Input
              id={`${id}-output`}
              inputMode='decimal'
              value={output}
              disabled={!canEdit || pending}
              onChange={(e) => setOutput(e.target.value)}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor={`${id}-currency`}>{t('usage.form.currency')}</Label>
            <select
              id={`${id}-currency`}
              className='h-9 rounded-md border bg-transparent px-3 text-sm'
              value={currency}
              disabled={!canEdit || pending}
              onChange={(e) => setCurrency(e.target.value as Currency)}
            >
              {currencies.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <p className='text-xs text-muted-foreground sm:col-span-4'>
            {t('usage.form.overrideHint')}
          </p>
        </div>
      )}

      {error && (
        <p role='alert' className='text-sm text-destructive'>
          {error}
        </p>
      )}
      {canEdit ? (
        <div>
          <Button type='submit' disabled={pending}>
            {pending && <Loader2 className='animate-spin' />}
            {t('usage.form.save')}
          </Button>
        </div>
      ) : (
        <p className='text-xs text-muted-foreground'>
          {t('usage.form.adminsOnly')}
        </p>
      )}
    </form>
  )
}
