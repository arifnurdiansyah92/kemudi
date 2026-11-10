import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { cn } from '@/lib/utils'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'

const SECTIONS = [
  ['profile', 'Profile'],
  ['account', 'Password and email'],
  ['notifications', 'Notifications'],
  ['apps', 'Connected apps'],
  ['appearance', 'Appearance'],
] as const

/** The signed-in user's own settings. */
export function Settings() {
  const path = useLocation({ select: (l) => l.pathname })
  const current = SECTIONS.find(([key]) => path.endsWith(`/settings/${key}`))
  return (
    <>
      <AppHeader
        crumbs={[
          { label: 'Your settings' },
          ...(current ? [{ label: current[1] }] : []),
        ]}
      />
      <Main fluid className='mx-auto w-full max-w-5xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>Your settings</h1>
        <div className='mt-6 grid gap-8 lg:grid-cols-[12rem_minmax(0,1fr)]'>
          <nav
            aria-label='Settings sections'
            className='lg:sticky lg:top-20 lg:self-start'
          >
            <ul className='flex gap-1 overflow-x-auto lg:flex-col'>
              {SECTIONS.map(([key, label]) => (
                <li key={key}>
                  <Link
                    to={`/settings/${key}` as '/settings/appearance'}
                    className={cn(
                      'block rounded-md px-3 py-1.5 text-sm whitespace-nowrap hover:bg-accent',
                      current?.[0] === key && 'bg-accent font-medium'
                    )}
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
          <div className='min-w-0'>
            <Outlet />
          </div>
        </div>
      </Main>
    </>
  )
}
