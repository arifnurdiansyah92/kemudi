import { useState } from 'react'
import { Plus, RotateCcw, TriangleAlert, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useSkillCatalog,
  type RoleSkill,
  type RoleSkillStatus,
  type RoleTemplate,
  type ScanLevel,
  type SkillOption,
  type SkillSource,
} from '@/lib/kemudi-ai/agent'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

/** The server's cap (kemudi_ai/awak/skills.py MAX_ROLE_SKILLS). */
const MAX_ROLE_SKILLS = 20

type Row = {
  slug: string
  title: string
  source: SkillSource | ''
  license: string
  version: number | null
  scan_level: ScanLevel
  status: RoleSkillStatus
}

function sameList(a: string[], b: string[]) {
  return a.length === b.length && a.every((x, i) => x === b[i])
}

function SourceBadge({ source }: { source: SkillSource }) {
  const { t } = useTranslation('agent')
  return (
    <Badge variant='outline' className='font-normal'>
      {t(`roles.skills.source.${source}`)}
    </Badge>
  )
}

/** The current version's worst scan finding. Medium and high carry the
 * danger color; clean and low stay neutral. */
function ScanBadge({ level }: { level: ScanLevel }) {
  const { t } = useTranslation('agent')
  const serious = level === 'medium' || level === 'high'
  return (
    <Badge
      variant='outline'
      className={cn(
        'font-normal',
        serious
          ? 'border-destructive/40 text-destructive'
          : 'text-muted-foreground'
      )}
    >
      {t(`roles.skills.scan.${level || 'clean'}`)}
    </Badge>
  )
}

/**
 * A role's skills: the chosen ones as rows, a searchable picker of the
 * enabled skills not chosen yet, and "Reset to defaults". `value` null is a
 * new role nobody touched yet: it follows the template's defaults.
 */
export function RoleSkills({
  value,
  onChange,
  template,
  details,
  readOnly,
}: {
  value: string[] | null
  onChange: (slugs: string[]) => void
  template: RoleTemplate
  /** The saved role's skills as the server described them. */
  details: RoleSkill[]
  readOnly: boolean
}) {
  const { t } = useTranslation('agent')
  const catalog = useSkillCatalog()
  const options = catalog.data?.skills ?? []
  const defaults = catalog.data?.template_defaults[template] ?? []
  const chosen = value ?? defaults
  const byslug = new Map(options.map((o) => [o.slug, o]))

  const rows: Row[] = chosen.map((slug) => {
    const opt = byslug.get(slug)
    if (opt) return { ...opt, status: 'ok' }
    const d = details.find((x) => x.slug === slug)
    if (d && (d.status !== 'ok' || !catalog.isSuccess)) return d
    // Not in the enabled list and nothing better known: treat as gone.
    return {
      slug,
      title: slug,
      source: '',
      license: '',
      version: null,
      scan_level: '',
      status: catalog.isSuccess ? 'missing' : 'ok',
    }
  })

  const available = options.filter((o) => !chosen.includes(o.slug))
  const full = chosen.length >= MAX_ROLE_SKILLS
  const noneInstalled = catalog.isSuccess && options.length === 0
  const titleOf = (slug: string) => byslug.get(slug)?.title ?? slug
  const templateName = t(`roles.templates.${template}`)

  return (
    <section
      className='grid gap-3 border-t pt-5'
      aria-labelledby='role-skills-title'
    >
      <div className='grid gap-1'>
        <h3 id='role-skills-title' className='text-sm font-medium'>
          {t('roles.skills.title')}
        </h3>
        <p className='text-xs text-muted-foreground'>
          {t('roles.skills.description')}
        </p>
      </div>

      {rows.length > 0 && (
        <ul
          className='divide-y rounded-lg border'
          aria-label={t('roles.skills.title')}
        >
          {rows.map((r) => (
            <SkillRow
              key={r.slug}
              row={r}
              readOnly={readOnly}
              onRemove={() => onChange(chosen.filter((s) => s !== r.slug))}
            />
          ))}
        </ul>
      )}

      {catalog.isError ? (
        <p role='alert' className='text-sm text-destructive'>
          {t('roles.skills.loadError')}
        </p>
      ) : noneInstalled ? (
        <p className='rounded-lg border border-dashed px-4 py-4 text-sm text-muted-foreground'>
          {t('roles.skills.noneInstalled')}
        </p>
      ) : (
        rows.length === 0 && (
          <p className='text-sm text-muted-foreground'>
            {t('roles.skills.none')}
          </p>
        )
      )}

      {!readOnly && !noneInstalled && !catalog.isError && (
        <div className='flex flex-wrap items-center gap-2'>
          <SkillPicker
            options={available}
            loading={catalog.isPending}
            disabled={full}
            onPick={(slug) => onChange([...chosen, slug])}
          />
          <Button
            type='button'
            size='sm'
            variant='ghost'
            disabled={!catalog.isSuccess || sameList(chosen, defaults)}
            onClick={() => onChange(defaults)}
          >
            <RotateCcw />
            {t('roles.skills.reset')}
          </Button>
        </div>
      )}
      {catalog.isSuccess && !noneInstalled && (
        <p className='text-xs text-muted-foreground'>
          {defaults.length
            ? t('roles.skills.defaultsFor', {
                template: templateName,
                skills: defaults.map(titleOf).join(', '),
              })
            : t('roles.skills.noDefaults', { template: templateName })}
          {full &&
            !readOnly &&
            ` ${t('roles.skills.limit', { max: MAX_ROLE_SKILLS })}`}
        </p>
      )}
    </section>
  )
}

function SkillRow({
  row,
  readOnly,
  onRemove,
}: {
  row: Row
  readOnly: boolean
  onRemove: () => void
}) {
  const { t } = useTranslation('agent')
  const problem = row.status !== 'ok'
  return (
    <li
      className={cn(
        'flex items-start gap-3 px-3 py-2',
        problem && 'bg-destructive/5'
      )}
    >
      <div className='grid min-w-0 flex-1 gap-1'>
        <p className='flex flex-wrap items-baseline gap-x-2 gap-y-0.5'>
          <span className='text-sm font-medium'>{row.title}</span>
          {row.title !== row.slug && (
            <span className='font-mono text-xs text-muted-foreground'>
              {row.slug}
            </span>
          )}
        </p>
        {row.source && (
          <p className='flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground'>
            <SourceBadge source={row.source} />
            {row.version !== null && <ScanBadge level={row.scan_level} />}
            <span>
              {row.license
                ? t('roles.skills.license', { license: row.license })
                : t('roles.skills.noLicense')}
            </span>
          </p>
        )}
        {row.status !== 'ok' && (
          <p className='flex items-start gap-1.5 text-xs text-destructive'>
            <TriangleAlert className='mt-px size-3.5 shrink-0' aria-hidden />
            {t(`roles.skills.status.${row.status}`)}
          </p>
        )}
      </div>
      {!readOnly && (
        <Button
          type='button'
          size='icon'
          variant='ghost'
          className='size-8 shrink-0 text-muted-foreground'
          aria-label={t('roles.skills.remove', { title: row.title })}
          onClick={onRemove}
        >
          <X />
        </Button>
      )}
    </li>
  )
}

function matches(o: SkillOption, q: string) {
  if (!q) return true
  return [o.slug, o.title, o.description].some((x) =>
    x.toLowerCase().includes(q)
  )
}

function SkillPicker({
  options,
  loading,
  disabled,
  onPick,
}: {
  options: SkillOption[]
  loading: boolean
  disabled: boolean
  onPick: (slug: string) => void
}) {
  const { t } = useTranslation('agent')
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const q = search.trim().toLowerCase()
  const shown = options.filter((o) => matches(o, q))

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) setSearch('')
      }}
    >
      <PopoverTrigger asChild>
        <Button type='button' size='sm' variant='outline' disabled={disabled}>
          <Plus />
          {t('roles.skills.add')}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align='start'
        className='w-96 max-w-[calc(100vw-2rem)] p-0'
      >
        <Command shouldFilter={false}>
          <CommandInput
            value={search}
            onValueChange={setSearch}
            placeholder={t('roles.skills.search')}
            aria-label={t('roles.skills.search')}
          />
          <CommandList>
            {loading ? (
              <p className='px-3 py-4 text-sm text-muted-foreground'>
                {t('roles.skills.loading')}
              </p>
            ) : options.length === 0 ? (
              <p className='px-3 py-4 text-sm text-muted-foreground'>
                {t('roles.skills.allAssigned')}
              </p>
            ) : shown.length === 0 ? (
              <p className='px-3 py-4 text-sm text-muted-foreground'>
                {t('roles.skills.noMatch', { query: search.trim() })}
              </p>
            ) : (
              <CommandGroup>
                {shown.map((o) => (
                  <CommandItem
                    key={o.slug}
                    value={o.slug}
                    onSelect={() => {
                      onPick(o.slug)
                      setOpen(false)
                      setSearch('')
                    }}
                    className='grid items-start gap-1 py-2'
                  >
                    <span className='flex flex-wrap items-baseline gap-x-2'>
                      <span className='text-sm font-medium'>{o.title}</span>
                      {o.title !== o.slug && (
                        <span className='font-mono text-xs text-muted-foreground'>
                          {o.slug}
                        </span>
                      )}
                    </span>
                    {o.description && (
                      <span className='line-clamp-2 text-xs text-muted-foreground'>
                        {o.description}
                      </span>
                    )}
                    <span className='flex flex-wrap items-center gap-1.5'>
                      <SourceBadge source={o.source} />
                      <ScanBadge level={o.scan_level} />
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
