import { Check, ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { StatusDot } from '@/features/story/parts'

type Option = { id: number; name: string; color?: string }

type OptionMenuProps = {
  label: string
  value: number | null | undefined
  options: Option[]
  onChange: (id: number | null) => void
  disabled?: boolean
  /** Shown when nothing is chosen; also adds a "clear" entry. */
  emptyLabel?: string
}

/** A pill showing the current choice, with a menu of the alternatives. */
export function OptionMenu({
  label,
  value,
  options,
  onChange,
  disabled,
  emptyLabel,
}: OptionMenuProps) {
  const { t } = useTranslation(['item', 'common'])
  const current = options.find((o) => o.id === value)
  const shown = current?.name ?? emptyLabel ?? t('common:status.none')
  const pill = (
    <span
      className={cn(
        'inline-flex h-7 max-w-56 items-center gap-1.5 rounded-full border bg-background px-2.5 text-xs font-medium',
        !disabled && 'hover:bg-accent',
        !current && 'text-muted-foreground'
      )}
    >
      {current?.color && <StatusDot color={current.color} />}
      <span className='truncate'>{shown}</span>
      {!disabled && <ChevronDown className='size-3 text-muted-foreground' />}
    </span>
  )
  if (disabled) return pill

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger
        className='rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring'
        aria-label={t('optionMenu.change', {
          label,
          value: shown,
          field: label.toLowerCase(),
        })}
      >
        {pill}
      </DropdownMenuTrigger>
      <DropdownMenuContent align='start' className='max-h-80 min-w-48'>
        {options.map((option) => (
          <DropdownMenuItem
            key={option.id}
            onSelect={() => option.id !== value && onChange(option.id)}
          >
            {option.color && <StatusDot color={option.color} />}
            <span className='truncate'>{option.name}</span>
            {option.id === value && <Check className='ms-auto' />}
          </DropdownMenuItem>
        ))}
        {emptyLabel && current && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onChange(null)}>
              {emptyLabel}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
