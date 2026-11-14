import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import {
  ExternalLink,
  Plus,
  RefreshCw,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  skillProblem,
  useAddMarketplace,
  useDeleteMarketplace,
  useInstallSkill,
  useMarketplacePlugins,
  useMarketplaces,
  useRefreshMarketplace,
  type Marketplace,
  type MarketplacePlugin,
  type MarketplaceSkill,
} from '@/lib/kemudi-ai/skills'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ScanBadge } from './badges'

/** The Marketplace tab: registered GitHub repos, their plugins and skills. */
export function MarketplaceTab({
  selected,
  onSelect,
  onOpenSkill,
}: {
  selected: number | null
  onSelect: (id: number) => void
  onOpenSkill: (slug: string) => void
}) {
  const { t } = useTranslation(['skills', 'common'])
  const markets = useMarketplaces()

  if (markets.isPending)
    return (
      <div className='grid gap-2' aria-label={t('market.loading')}>
        {[0, 1].map((i) => (
          <Skeleton key={i} className='h-16 w-full' />
        ))}
      </div>
    )
  if (markets.isError)
    return (
      <p role='alert' className='text-sm'>
        {t('market.loadError')}{' '}
        <Button
          variant='link'
          className='h-auto p-0'
          onClick={() => markets.refetch()}
        >
          {t('common:actions.retry')}
        </Button>
      </p>
    )
  const rows = markets.data
  const current = rows.find((m) => m.id === selected) ?? rows[0] ?? null

  return (
    <div className='grid gap-6'>
      <div className='grid gap-3'>
        <AddMarketplace onAdded={onSelect} />
        {rows.length > 0 && (
          <ul
            className='divide-y rounded-lg border bg-card'
            aria-label={t('market.listLabel')}
          >
            {rows.map((m) => (
              <MarketplaceRow
                key={m.id}
                market={m}
                selected={m.id === current?.id}
                onSelect={() => onSelect(m.id)}
              />
            ))}
          </ul>
        )}
      </div>
      {current && <PluginList market={current} onOpenSkill={onOpenSkill} />}
    </div>
  )
}

function AddMarketplace({ onAdded }: { onAdded: (id: number) => void }) {
  const { t } = useTranslation('skills')
  const [repo, setRepo] = useState('')
  const [error, setError] = useState<string | null>(null)
  const add = useAddMarketplace()
  const refresh = useRefreshMarketplace()

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!repo.trim()) return
    setError(null)
    add.mutate(repo.trim(), {
      onSuccess: (m) => {
        setRepo('')
        onAdded(m.id)
        toast.success(t('market.added', { repo: m.repo }))
        refresh.mutate(m.id, {
          onError: (err) =>
            toast.error(t('market.refreshFailed', { name: m.repo }), {
              description: skillProblem(err).problems.join(' '),
            }),
        })
      },
      onError: (err) => setError(skillProblem(err).message),
    })
  }

  return (
    <form onSubmit={submit} className='grid gap-1.5'>
      <Label htmlFor='marketplace-repo'>{t('market.addLabel')}</Label>
      <div className='flex flex-wrap gap-2'>
        <Input
          id='marketplace-repo'
          value={repo}
          onChange={(e) => {
            setRepo(e.target.value)
            setError(null)
          }}
          placeholder={t('market.addPlaceholder')}
          aria-invalid={error ? true : undefined}
          aria-describedby='marketplace-repo-hint'
          className='max-w-md min-w-0 flex-1 font-mono text-sm'
          autoComplete='off'
          spellCheck={false}
        />
        <Button
          type='submit'
          variant='outline'
          disabled={!repo.trim() || add.isPending}
        >
          <Plus />
          {add.isPending ? t('market.adding') : t('market.add')}
        </Button>
      </div>
      <p
        id='marketplace-repo-hint'
        role={error ? 'alert' : undefined}
        className={cn(
          'text-xs',
          error ? 'text-destructive' : 'text-muted-foreground'
        )}
      >
        {error ?? t('market.addHint')}
      </p>
    </form>
  )
}

function MarketplaceRow({
  market: m,
  selected,
  onSelect,
}: {
  market: Marketplace
  selected: boolean
  onSelect: () => void
}) {
  const { t } = useTranslation('skills')
  const f = useFormat()
  const refresh = useRefreshMarketplace()
  const del = useDeleteMarketplace()
  const [confirm, setConfirm] = useState(false)

  const doRefresh = () =>
    refresh.mutate(m.id, {
      onSuccess: (r) =>
        toast.success(
          t('market.refreshed', { name: r.name, count: r.skill_count })
        ),
      onError: (err) =>
        toast.error(t('market.refreshFailed', { name: m.name }), {
          description: skillProblem(err).problems.join(' '),
        }),
    })

  return (
    <li
      className={cn(
        'flex flex-wrap items-center gap-3 px-4 py-3',
        selected && 'bg-muted/40'
      )}
    >
      <button
        type='button'
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        className='grid min-w-0 flex-1 gap-1 rounded-md text-start outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50'
      >
        <span className='flex flex-wrap items-baseline gap-x-2 gap-y-0.5'>
          <span
            className={cn(
              'text-sm hover:underline hover:underline-offset-4',
              selected ? 'font-semibold' : 'font-medium'
            )}
          >
            {m.name}
          </span>
          {m.name !== m.repo && (
            <span className='font-mono text-xs text-muted-foreground'>
              {m.repo}
              {m.ref && `@${m.ref}`}
            </span>
          )}
          {m.builtin && (
            <Badge variant='outline' className='font-normal'>
              {t('market.builtin')}
            </Badge>
          )}
        </span>
        <span className='flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground'>
          {m.last_sha ? (
            <>
              <span>
                {t('market.counts', {
                  skills: t('market.skillCount', { count: m.skill_count }),
                  plugins: t('market.pluginCount', { count: m.plugin_count }),
                })}
              </span>
              {m.last_fetched_at && (
                <span>
                  {t('market.fetched', { when: f.timeAgo(m.last_fetched_at) })}
                </span>
              )}
              <span className='font-mono' title={m.last_sha}>
                {m.last_sha.slice(0, 7)}
              </span>
            </>
          ) : (
            <span>{t('market.notFetched')}</span>
          )}
        </span>
        {m.error && (
          <span className='flex items-start gap-1 text-xs text-destructive'>
            <TriangleAlert className='mt-px size-3.5 shrink-0' aria-hidden />
            {m.error}
          </span>
        )}
      </button>
      <div className='flex items-center gap-1'>
        <Button
          size='sm'
          variant='ghost'
          onClick={doRefresh}
          disabled={refresh.isPending}
          aria-label={t('market.refreshName', { name: m.name })}
        >
          <RefreshCw
            className={cn(refresh.isPending && 'animate-spin')}
            aria-hidden
          />
          {refresh.isPending ? t('market.refreshing') : t('market.refresh')}
        </Button>
        {!m.builtin && (
          <Button
            size='icon'
            variant='ghost'
            className='size-8 text-muted-foreground hover:text-destructive'
            onClick={() => setConfirm(true)}
            aria-label={t('market.removeName', { name: m.name })}
          >
            <Trash2 />
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={t('market.removeTitle', { name: m.name })}
        desc={t('market.removeBody')}
        confirmText={t('market.remove')}
        destructive
        isLoading={del.isPending}
        handleConfirm={() =>
          del.mutate(m.id, {
            onSuccess: () => setConfirm(false),
            onError: (err) => {
              setConfirm(false)
              toast.error(skillProblem(err).message)
            },
          })
        }
      />
    </li>
  )
}

function PluginList({
  market,
  onOpenSkill,
}: {
  market: Marketplace
  onOpenSkill: (slug: string) => void
}) {
  const { t } = useTranslation(['skills', 'common'])
  const listing = useMarketplacePlugins(market.id)

  let body: React.ReactNode
  if (listing.isPending)
    body = <Skeleton className='h-40 w-full' aria-label={t('market.loading')} />
  else if (listing.isError)
    body = (
      <p role='alert' className='text-sm'>
        {t('market.pluginsError')}{' '}
        <Button
          variant='link'
          className='h-auto p-0'
          onClick={() => listing.refetch()}
        >
          {t('common:actions.retry')}
        </Button>
      </p>
    )
  else if (!listing.data.refreshed)
    body = (
      <div className='rounded-lg border border-dashed p-8 text-center'>
        <p className='font-medium'>{t('market.notFetchedTitle')}</p>
        <p className='mx-auto mt-1 max-w-prose text-sm text-muted-foreground'>
          {t('market.notFetchedHint')}
        </p>
      </div>
    )
  else if (listing.data.plugins.length === 0)
    body = (
      <p className='text-sm text-muted-foreground'>{t('market.noPlugins')}</p>
    )
  else
    body = (
      <div className='grid gap-6'>
        {listing.data.plugins.map((p) => (
          <PluginSection
            key={p.name}
            plugin={p}
            marketId={market.id}
            onOpenSkill={onOpenSkill}
          />
        ))}
      </div>
    )

  return (
    <section className='grid gap-3' aria-labelledby='marketplace-plugins'>
      <div className='flex flex-wrap items-baseline justify-between gap-2 border-b pb-2'>
        <h2 id='marketplace-plugins' className='text-base font-semibold'>
          {market.name}
        </h2>
        <a
          href={
            market.last_sha
              ? `${market.url}/tree/${market.last_sha}`
              : market.url
          }
          target='_blank'
          rel='noreferrer noopener'
          className='inline-flex items-center gap-1 font-mono text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline'
        >
          {market.repo}
          {market.last_sha && `@${market.last_sha.slice(0, 7)}`}
          <ExternalLink className='size-3' aria-hidden />
        </a>
      </div>
      {market.description && (
        <p className='max-w-prose text-sm text-muted-foreground'>
          {market.description}
        </p>
      )}
      {body}
    </section>
  )
}

function PluginSection({
  plugin: p,
  marketId,
  onOpenSkill,
}: {
  plugin: MarketplacePlugin
  marketId: number
  onOpenSkill: (slug: string) => void
}) {
  const { t } = useTranslation('skills')
  const external =
    p.source.type === 'github' && typeof p.source.repo === 'string'
      ? p.source.repo
      : null
  return (
    <section className='grid gap-2'>
      <div className='grid gap-0.5'>
        <h3
          className={cn(
            'flex flex-wrap items-baseline gap-x-2 text-sm font-medium',
            !p.supported && 'text-muted-foreground'
          )}
        >
          {p.name}
          {p.version && (
            <span className='text-xs font-normal text-muted-foreground tabular-nums'>
              {p.version}
            </span>
          )}
          {p.category && (
            <Badge variant='outline' className='font-normal'>
              {p.category}
            </Badge>
          )}
          {external && (
            <span className='font-mono text-xs font-normal text-muted-foreground'>
              {t('market.from', { repo: external })}
            </span>
          )}
        </h3>
        {p.description && (
          <p className='line-clamp-2 max-w-prose text-xs text-muted-foreground'>
            {p.description}
          </p>
        )}
      </div>
      {!p.supported ? (
        <p className='rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground'>
          {t('market.unsupported', { reason: p.reason })}
        </p>
      ) : p.skills.length === 0 ? (
        <p className='text-xs text-muted-foreground'>
          {p.reason || t('market.noSkills')}
        </p>
      ) : (
        <ul className='divide-y rounded-lg border bg-card'>
          {p.skills.map((s) => (
            <SkillRow
              key={s.path || s.name}
              skill={s}
              plugin={p.name}
              marketId={marketId}
              onOpenSkill={onOpenSkill}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

function SkillRow({
  skill: s,
  plugin,
  marketId,
  onOpenSkill,
}: {
  skill: MarketplaceSkill
  plugin: string
  marketId: number
  onOpenSkill: (slug: string) => void
}) {
  const { t } = useTranslation('skills')
  const install = useInstallSkill()

  const doInstall = () =>
    install.mutate(
      { id: marketId, plugin, skill: s.name },
      {
        onSuccess: (d) =>
          toast.success(t('market.installed', { name: d.slug }), {
            description: t('market.installedHint'),
            action: {
              label: t('market.open'),
              onClick: () => onOpenSkill(d.slug),
            },
          }),
        onError: (err) => {
          const p = skillProblem(err)
          toast.error(t('market.installFailed', { name: s.name }), {
            description: [p.message, ...p.problems]
              .filter((x, i, a) => a.indexOf(x) === i)
              .join(' '),
          })
        },
      }
    )

  let action: React.ReactNode
  if (s.installed?.same_origin)
    action = (
      <Button
        size='sm'
        variant='ghost'
        onClick={() => onOpenSkill(s.installed!.slug)}
      >
        {t('market.installedVersion', { version: s.installed.version })}
      </Button>
    )
  else if (s.installed)
    action = (
      <span className='max-w-40 text-end text-xs text-muted-foreground'>
        {t('market.nameTaken', {
          source: t(`source.${s.installed.source}`),
        })}
      </span>
    )
  else
    action = (
      <Button
        size='sm'
        variant='outline'
        disabled={!s.valid || install.isPending}
        onClick={doInstall}
        aria-label={t('market.installName', { name: s.name })}
      >
        {install.isPending ? t('market.installing') : t('market.install')}
      </Button>
    )

  return (
    <li className='flex items-center gap-3 px-4 py-3'>
      <div className='grid min-w-0 flex-1 gap-1'>
        <span
          className={cn(
            'font-mono text-sm',
            s.valid ? 'font-medium' : 'text-muted-foreground'
          )}
        >
          {s.name}
        </span>
        {s.description && (
          <span className='line-clamp-2 text-xs text-muted-foreground'>
            {s.description}
          </span>
        )}
        <span className='flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground'>
          {s.version && (
            <span className='tabular-nums'>
              {t('market.skillVersion', { version: s.version })}
            </span>
          )}
          {s.license ? (
            <span>{t('list.license', { license: s.license })}</span>
          ) : (
            <span className='inline-flex items-center gap-1'>
              <TriangleAlert className='size-3.5' aria-hidden />
              {t('list.noLicense')}
            </span>
          )}
          {s.valid && <ScanBadge level={s.scan_level} />}
        </span>
        {!s.valid && s.problems.length > 0 && (
          <span className='text-xs text-destructive'>
            {t('market.invalid', { problems: s.problems.join('; ') })}
          </span>
        )}
      </div>
      {action}
    </li>
  )
}
