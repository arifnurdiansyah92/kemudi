import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'

const SECTIONS = [
  'profile',
  'account',
  'notifications',
  'apps',
  'appearance',
] as const

/** The signed-in user's own settings. */
export function Settings() {
  const { t } = useTranslation('settings')
  const path = useLocation({ select: (l) => l.pathname })
  const current = SECTIONS.find((key) => path.endsWith(`/settings/${key}`))
  return (
    <>
      <AppHeader
        crumbs={[
          { label: t('nav.title') },
          ...(current ? [{ label: t(`nav.sections.${current}`) }] : []),
        ]}
      />
      <Main width='list'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('nav.title')}
        </h1>
        <div className='mt-6 grid gap-8 lg:grid-cols-[12rem_minmax(0,1fr)]'>
          <nav
            aria-label={t('nav.label')}
            className='lg:sticky lg:top-20 lg:self-start'
          >
            <ul className='flex gap-1 overflow-x-auto lg:flex-col'>
              {SECTIONS.map((key) => (
                <li key={key}>
                  <Link
                    to={`/settings/${key}` as '/settings/appearance'}
                    className={cn(
                      'block rounded-md px-3 py-1.5 text-sm whitespace-nowrap hover:bg-accent',
                      current === key && 'bg-accent font-medium'
                    )}
                  >
                    {t(`nav.sections.${key}`)}
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
