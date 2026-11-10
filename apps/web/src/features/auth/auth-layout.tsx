import { useTranslation } from 'react-i18next'
import { Logo } from '@/assets/logo'

type AuthLayoutProps = {
  title: string
  description?: React.ReactNode
  children: React.ReactNode
}

/**
 * Two panes on wide screens: the helm on deep sea ink, and the form on the
 * work surface. On phones only the form shows, under a small wordmark.
 */
export function AuthLayout({ title, description, children }: AuthLayoutProps) {
  const { t } = useTranslation('auth')
  return (
    <div className='grid min-h-svh lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]'>
      <aside className='relative hidden overflow-hidden bg-sidebar text-sidebar-foreground lg:flex lg:flex-col lg:justify-between lg:p-12'>
        <div className='flex items-center gap-2.5 text-sidebar-accent-foreground'>
          <Logo className='size-7 text-sidebar-primary' />
          <span className='text-lg font-semibold tracking-tight'>Kemudi</span>
        </div>
        <Logo
          className='pointer-events-none absolute -end-40 top-1/2 size-[36rem] -translate-y-1/2 text-sidebar-border'
          strokeWidth={0.6}
        />
        <p className='relative max-w-xs text-2xl leading-snug font-medium text-sidebar-accent-foreground'>
          {t('layout.tagline')}
        </p>
      </aside>

      <main className='flex items-center justify-center px-4 py-10 sm:px-8'>
        <div className='w-full max-w-sm'>
          <div className='mb-8 flex items-center gap-2 lg:hidden'>
            <Logo className='size-6 text-brass' />
            <span className='font-semibold tracking-tight'>Kemudi</span>
          </div>
          <h1 className='text-2xl font-semibold tracking-tight'>{title}</h1>
          {description && (
            <p className='mt-1.5 text-sm text-muted-foreground'>
              {description}
            </p>
          )}
          <div className='mt-8'>{children}</div>
        </div>
      </main>
    </div>
  )
}
