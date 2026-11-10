import { Link, Outlet, useLocation } from '@tanstack/react-router'
import { cn } from '@/lib/utils'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { useProject } from '@/features/project/use-project'

const SECTIONS = [
  ['general', 'General'],
  ['members', 'Members'],
  ['roles', 'Roles and permissions'],
  ['attributes', 'Statuses and values'],
  ['custom-fields', 'Custom fields'],
  ['tags', 'Tags'],
  ['webhooks', 'Webhooks'],
  ['data', 'Import and export'],
  ['sprint-access', 'Sprint access'],
] as const

export function ProjectSettingsLayout() {
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
          { label: 'Settings' },
          ...(current ? [{ label: current[1] }] : []),
        ]}
      />
      <Main fluid className='mx-auto w-full max-w-6xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          Project settings
        </h1>
        {!project.i_am_admin ? (
          <p className='mt-4 text-sm text-muted-foreground'>
            Only project admins can change settings. Ask an admin of{' '}
            {project.name} if something needs changing.
          </p>
        ) : (
          <div className='mt-6 grid gap-8 lg:grid-cols-[13rem_minmax(0,1fr)]'>
            <nav
              aria-label='Settings sections'
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
