import { cn } from '@/lib/utils'

/**
 * One width policy for every page, always centred:
 * - board: kanban and taskboard use all the space;
 * - table: wide data tables (issues);
 * - list: working lists and settings (backlog, epics, wiki, home);
 * - reading: profiles, team, project lists;
 * - form: single-column forms.
 */
const widths = {
  board: '',
  table: 'max-w-7xl',
  list: 'max-w-6xl',
  reading: 'max-w-4xl',
  form: 'max-w-2xl',
} as const

type MainProps = React.HTMLAttributes<HTMLElement> & {
  fixed?: boolean
  width?: keyof typeof widths
  ref?: React.Ref<HTMLElement>
}

export function Main({
  fixed,
  className,
  width = 'list',
  ...props
}: MainProps) {
  return (
    <main
      data-layout={fixed ? 'fixed' : 'auto'}
      className={cn(
        'mx-auto w-full px-4 py-6',
        widths[width],
        // A fixed layout fills the viewport height and scrolls inside.
        fixed && 'flex grow flex-col overflow-hidden',
        className
      )}
      {...props}
    />
  )
}
