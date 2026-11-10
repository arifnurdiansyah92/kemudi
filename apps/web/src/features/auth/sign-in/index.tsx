import { useSearch } from '@tanstack/react-router'
import { AuthLayout } from '../auth-layout'
import { UserAuthForm } from './components/user-auth-form'

export function SignIn() {
  const { redirect } = useSearch({ from: '/(auth)/sign-in' })

  return (
    <AuthLayout
      title='Sign in'
      description='Use your Kemudi username or email and password.'
    >
      <UserAuthForm redirectTo={redirect} />
    </AuthLayout>
  )
}
