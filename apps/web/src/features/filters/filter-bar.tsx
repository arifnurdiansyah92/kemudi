import { useMemo, useState } from 'react'
import { Check, ListFilter, Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { StatusDot } from '@/features/story/parts'
import {
  emptyFilters,
  isFiltering,
  type Facet,
  type FacetValue,
  type FilterState,
} from './apply'
import { SavedFilters } from './saved-filters'

/** Counts how many items carry each option, for the menus. */
function useCounts<T>(items: T[], facet: Facet<T>) {
  return useMemo(() => {
    const counts = new Map<FacetValue, number>()
    for (const item of items)
      for (const v of facet.values(item))
        counts.set(v, (counts.get(v) ?? 0) + 1)
    return counts
  }, [items, facet])
}

type FilterBarProps<T> = {
  /** Enables named saved filters, stored per user under this key. */
  savedKey?: string
  items: T[]
  facets: Facet<T>[]
  value: FilterState
  onChange: (f: FilterState) => void
  placeholder?: string
  className?: string
}

export function FilterBar<T>({
  savedKey,
  items,
  facets,
  value,
  onChange,
  placeholder = 'Search by subject or #ref',
  className,
}: FilterBarProps<T>) {
  const active = facets.flatMap((facet) =>
    (value.facets[facet.key] ?? []).map((v) => ({
      facet,
      option: facet.options.find((o) => o.value === v),
      v,
    }))
  )
  const toggle = (key: string, v: FacetValue) => {
    const current = value.facets[key] ?? []
    onChange({
      ...value,
      facets: {
        ...value.facets,
        [key]: current.includes(v)
          ? current.filter((x) => x !== v)
          : [...current, v],
      },
    })
  }

  return (
    <div className={cn('grid gap-2', className)}>
      <div className='flex flex-wrap items-center gap-2'>
        <div className='relative min-w-48 flex-1 sm:max-w-72'>
          <Search
            aria-hidden='true'
            className='absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground'
          />
          <Input
            value={value.q}
            onChange={(e) => onChange({ ...value, q: e.target.value })}
            placeholder={placeholder}
            aria-label='Search'
            className='h-8 ps-8'
          />
        </div>
        {facets.map((facet) => (
          <FacetMenu
            key={facet.key}
            items={items}
            facet={facet}
            selected={value.facets[facet.key] ?? []}
            onToggle={(v) => toggle(facet.key, v)}
          />
        ))}
        {savedKey && (
          <SavedFilters
            storageKey={savedKey}
            value={value}
            onApply={onChange}
          />
        )}
        {isFiltering(value) && (
          <Button
            variant='ghost'
            size='sm'
            className='h-8 text-muted-foreground'
            onClick={() => onChange(emptyFilters)}
          >
            Clear filters
          </Button>
        )}
      </div>
      {active.length > 0 && (
        <ul className='flex flex-wrap gap-1.5' aria-label='Active filters'>
          {active.map(({ facet, option, v }) => (
            <li key={`${facet.key}-${v}`}>
              <button
                onClick={() => toggle(facet.key, v)}
                aria-label={`Remove filter ${facet.label}: ${option?.label ?? v}`}
                className='inline-flex h-6 items-center gap-1.5 rounded-full border bg-background px-2 text-xs hover:bg-accent'
              >
                <span className='text-muted-foreground'>{facet.label}</span>
                {option?.color && <StatusDot color={option.color} />}
                {option?.label ?? String(v)}
                <X className='size-3 text-muted-foreground' />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function FacetMenu<T>({
  items,
  facet,
  selected,
  onToggle,
}: {
  items: T[]
  facet: Facet<T>
  selected: FacetValue[]
  onToggle: (v: FacetValue) => void
}) {
  const [open, setOpen] = useState(false)
  const counts = useCounts(items, facet)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant='outline'
          size='sm'
          aria-label={`Filter by ${facet.label.toLowerCase()}${selected.length ? `, ${selected.length} selected` : ''}`}
          className={cn('h-8 border-dashed', selected.length && 'border-solid')}
        >
          <ListFilter className='size-3.5' />
          {facet.label}
          {selected.length > 0 && (
            <span className='rounded-sm bg-secondary px-1 text-xs tabular-nums'>
              {selected.length}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent className='w-60 p-0' align='start'>
        <Command>
          {facet.options.length > 7 && (
            <CommandInput placeholder={`Find ${facet.label.toLowerCase()}`} />
          )}
          <CommandList>
            <CommandEmpty>Nothing matches.</CommandEmpty>
            <CommandGroup>
              {facet.options.map((option) => {
                const on = selected.includes(option.value)
                return (
                  <CommandItem
                    key={String(option.value)}
                    value={`${option.label} ${option.value}`}
                    onSelect={() => onToggle(option.value)}
                  >
                    <span
                      className={cn(
                        'flex size-4 items-center justify-center rounded-sm border',
                        on &&
                          'border-primary bg-primary text-primary-foreground'
                      )}
                    >
                      {on && <Check className='size-3' />}
                    </span>
                    {option.color && <StatusDot color={option.color} />}
                    <span className='truncate'>{option.label}</span>
                    <span className='ms-auto text-xs text-muted-foreground tabular-nums'>
                      {counts.get(option.value) ?? 0}
                    </span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
