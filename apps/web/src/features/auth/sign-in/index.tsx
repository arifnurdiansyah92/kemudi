import { Link, useSearch } from '@tanstack/react-router'
import { AuthLayout } from '../auth-layout'
import { useRegistrationOpen } from '../sign-up/use-registration-open'
import { UserAuthForm } from './components/user-auth-form'

export function SignIn() {
  const { redirect } = useSearch({ from: '/(auth)/sign-in' })
  const open = useRegistrationOpen()

  return (
    <AuthLayout
      title='Sign in'
      description='Use your Kemudi username or email and password.'
    >
      <UserAuthForm redirectTo={redirect} />
      {open.data && (
        <p className='mt-6 text-sm text-muted-foreground'>
          New here?{' '}
          <Link
            to='/sign-up'
            className='text-foreground underline underline-offset-4'
          >
            Create an account
          </Link>
        </p>
      )}
    </AuthLayout>
  )
}
