import { Link, useSearch } from '@tanstack/react-router'
import { Trans, useTranslation } from 'react-i18next'
import { AuthLayout } from '../auth-layout'
import { useRegistrationOpen } from '../sign-up/use-registration-open'
import { UserAuthForm } from './components/user-auth-form'

export function SignIn() {
  const { t } = useTranslation('auth')
  const { redirect } = useSearch({ from: '/(auth)/sign-in' })
  const open = useRegistrationOpen()

  return (
    <AuthLayout title={t('signIn.title')} description={t('signIn.description')}>
      <UserAuthForm redirectTo={redirect} />
      {open.data && (
        <p className='mt-6 text-sm text-muted-foreground'>
          <Trans
            t={t}
            i18nKey='signIn.newHere'
            components={{
              link: (
                <Link
                  to='/sign-up'
                  className='text-foreground underline underline-offset-4'
                />
              ),
            }}
          />
        </p>
      )}
    </AuthLayout>
  )
}
