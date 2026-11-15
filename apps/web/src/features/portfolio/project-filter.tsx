import { useState } from 'react'
import { ListFilter } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { PortfolioProject } from '@/lib/kemudi-ai/portfolio'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

/**
 * Which projects the portfolio brings in. Kept as exclusions, so every
 * project is in by default and a new project shows up without a visit here.
 */
export function ProjectFilter({
  projects,
  excluded,
  onChange,
}: {
  projects: PortfolioProject[]
  excluded: Set<string>
  onChange: (excluded: string[]) => void
}) {
  const { t } = useTranslation('portfolio')
  const [query, setQuery] = useState('')
  const total = projects.length
  const included = projects.filter((p) => !excluded.has(p.slug)).length
  const q = query.trim().toLowerCase()
  const shown = q
    ? projects.filter(
        (p) =>
          p.name.toLowerCase().includes(q) || p.slug.toLowerCase().includes(q)
      )
    : projects

  const toggle = (slug: string, include: boolean) => {
    const next = new Set(excluded)
    if (include) next.delete(slug)
    else next.add(slug)
    onChange([...next])
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant='outline' size='sm'>
          <ListFilter />
          {included === total
            ? t('filter.buttonAll', { total })
            : t('filter.button', { included, total })}
        </Button>
      </PopoverTrigger>
      <PopoverContent align='end' className='w-80 p-0'>
        <div className='grid gap-2 border-b p-3'>
          <Input
            aria-label={t('filter.search')}
            placeholder={t('filter.search')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className='h-8'
          />
          <div className='flex gap-2'>
            <Button
              variant='ghost'
              size='sm'
              className='h-7 px-2'
              onClick={() => onChange([])}
            >
              {t('filter.all')}
            </Button>
            <Button
              variant='ghost'
              size='sm'
              className='h-7 px-2'
              onClick={() => onChange(projects.map((p) => p.slug))}
            >
              {t('filter.none')}
            </Button>
          </div>
        </div>
        <ul className='max-h-72 overflow-y-auto p-1'>
          {shown.map((p) => {
            const id = `portfolio-include-${p.slug}`
            return (
              <li key={p.id}>
                <label
                  htmlFor={id}
                  className='flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent'
                >
                  <Checkbox
                    id={id}
                    checked={!excluded.has(p.slug)}
                    onCheckedChange={(v) => toggle(p.slug, v === true)}
                  />
                  <span className='truncate'>{p.name}</span>
                </label>
              </li>
            )
          })}
          {shown.length === 0 && (
            <li className='px-2 py-3 text-sm text-muted-foreground'>
              {t('filter.empty')}
            </li>
          )}
        </ul>
        <p className='border-t p-3 text-xs text-muted-foreground'>
          {t('filter.hint')}
        </p>
      </PopoverContent>
    </Popover>
  )
}
