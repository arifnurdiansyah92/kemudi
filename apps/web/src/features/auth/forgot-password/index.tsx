import { Link } from '@tanstack/react-router'
import { AuthLayout } from '../auth-layout'
import { ForgotPasswordForm } from './components/forgot-password-form'

export function ForgotPassword() {
  return (
    <AuthLayout
      title='Reset your password'
      description='We will email you a link to choose a new password.'
    >
      <ForgotPasswordForm />
      <p className='mt-6 text-sm text-muted-foreground'>
        Remembered it?{' '}
        <Link
          to='/sign-in'
          className='text-foreground underline underline-offset-4'
        >
          Back to sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
