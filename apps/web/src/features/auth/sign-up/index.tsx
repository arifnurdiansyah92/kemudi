import { Link, useNavigate } from '@tanstack/react-router'
import { Trans, useTranslation } from 'react-i18next'
import { registerPublic } from '@/lib/taiga/client'
import { Skeleton } from '@/components/ui/skeleton'
import { AuthLayout } from '../auth-layout'
import { AccountForm } from './account-form'
import { useRegistrationOpen } from './use-registration-open'

export function SignUp() {
  const { t } = useTranslation('auth')
  const navigate = useNavigate()
  const open = useRegistrationOpen()
  return (
    <AuthLayout
      title={t('signUp.title')}
      description={
        <Trans
          t={t}
          i18nKey='signUp.haveAccount'
          components={{
            link: (
              <Link
                to='/sign-in'
                className='text-foreground underline underline-offset-4'
              />
            ),
          }}
        />
      }
    >
      {open.isPending ? (
        <Skeleton className='h-64 w-full' />
      ) : open.data ? (
        <AccountForm
          submitLabel={t('signUp.submit')}
          onSubmit={async (account) => {
            await registerPublic(account)
            navigate({ to: '/', replace: true })
          }}
        />
      ) : (
        <p className='text-sm text-muted-foreground'>{t('signUp.closed')}</p>
      )}
    </AuthLayout>
  )
}
