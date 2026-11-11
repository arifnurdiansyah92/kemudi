import { Link } from '@tanstack/react-router'
import { Trans, useTranslation } from 'react-i18next'
import { AuthLayout } from '../auth-layout'
import { ForgotPasswordForm } from './components/forgot-password-form'

export function ForgotPassword() {
  const { t } = useTranslation('auth')
  return (
    <AuthLayout
      title={t('forgotPassword.title')}
      description={t('forgotPassword.description')}
    >
      <ForgotPasswordForm />
      <p className='mt-6 text-sm text-muted-foreground'>
        <Trans
          t={t}
          i18nKey='forgotPassword.remembered'
          components={{
            link: (
              <Link
                to='/sign-in'
                className='text-foreground underline underline-offset-4'
              />
            ),
          }}
        />
      </p>
    </AuthLayout>
  )
}
