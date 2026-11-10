import { Fragment } from 'react'
import { Link, type LinkProps } from '@tanstack/react-router'
import { ChevronRight } from 'lucide-react'
import { Header } from '@/components/layout/header'
import { Search } from '@/components/search'
import { ThemeSwitch } from '@/components/theme-switch'

type Crumb = { label: string; to?: LinkProps['to']; params?: object }

/** Top bar: where you are, then search and theme. */
export function AppHeader({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <Header fixed>
      <nav aria-label='Breadcrumb' className='min-w-0 flex-1'>
        <ol className='flex min-w-0 items-center gap-1.5 text-sm'>
          {crumbs.map((crumb, i) => {
            const last = i === crumbs.length - 1
            return (
              <Fragment key={crumb.label + i}>
                {i > 0 && (
                  <ChevronRight
                    aria-hidden='true'
                    className='size-3.5 shrink-0 text-muted-foreground'
                  />
                )}
                <li className='min-w-0 truncate'>
                  {crumb.to && !last ? (
                    <Link
                      to={crumb.to}
                      params={crumb.params as never}
                      className='text-muted-foreground hover:text-foreground'
                    >
                      {crumb.label}
                    </Link>
                  ) : (
                    <span
                      aria-current={last ? 'page' : undefined}
                      className={last ? 'font-medium' : 'text-muted-foreground'}
                    >
                      {crumb.label}
                    </span>
                  )}
                </li>
              </Fragment>
            )
          })}
        </ol>
      </nav>
      <Search className='max-sm:hidden' placeholder='Jump to…' />
      <ThemeSwitch />
    </Header>
  )
}
