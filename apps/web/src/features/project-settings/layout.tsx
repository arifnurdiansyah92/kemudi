import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { useProject } from '@/features/project/use-project'

/** Route segment and its nav label key in the admin namespace. */
const SECTIONS = [
  ['general', 'nav.general'],
  ['members', 'nav.members'],
  ['roles', 'nav.roles'],
  ['attributes', 'nav.values'],
  ['custom-fields', 'nav.customFields'],
  ['tags', 'nav.tags'],
  ['webhooks', 'nav.webhooks'],
  ['integrations', 'nav.integrations'],
  ['data', 'nav.exportImport'],
  ['sprint-access', 'nav.sprintAccess'],
] as const

export function ProjectSettingsLayout() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  const path = useLocation({ select: (l) => l.pathname })
  const current = SECTIONS.find(([key]) => path.includes(`/settings/${key}`))

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: t('common:terms.settings') },
          ...(current ? [{ label: t(current[1]) }] : []),
        ]}
      />
      <Main fluid className='mx-auto w-full max-w-6xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('nav.title')}
        </h1>
        {!project.i_am_admin ? (
          <p className='mt-4 text-sm text-muted-foreground'>
            {t('nav.notAdmin', { project: project.name })}
          </p>
        ) : (
          <div className='mt-6 grid gap-8 lg:grid-cols-[13rem_minmax(0,1fr)]'>
            <nav
              aria-label={t('nav.sectionsLabel')}
              className='lg:sticky lg:top-20 lg:self-start'
            >
              <ul className='flex gap-1 overflow-x-auto lg:flex-col'>
                {SECTIONS.map(([key, label]) => (
                  <li key={key}>
                    <Link
                      to={
                        `/p/$slug/settings/${key}` as '/p/$slug/settings/general'
                      }
                      params={{ slug: project.slug }}
                      className={cn(
                        'block rounded-md px-3 py-1.5 text-sm whitespace-nowrap hover:bg-accent',
                        current?.[0] === key && 'bg-accent font-medium'
                      )}
                    >
                      {t(label)}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
            <div className='min-w-0'>
              <Outlet />
            </div>
          </div>
        )}
      </Main>
    </>
  )
}

/** A titled block within a settings page. */
export function SettingsSection({
  title,
  description,
  children,
  danger,
}: {
  title: string
  description?: React.ReactNode
  children: React.ReactNode
  danger?: boolean
}) {
  return (
    <section
      className={cn(
        'rounded-lg border bg-card p-5',
        danger && 'border-destructive/40'
      )}
    >
      <h2 className={cn('font-semibold', danger && 'text-destructive')}>
        {title}
      </h2>
      {description && (
        <p className='mt-1 text-sm text-muted-foreground'>{description}</p>
      )}
      <div className='mt-4'>{children}</div>
    </section>
  )
}
