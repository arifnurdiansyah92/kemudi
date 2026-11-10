import { Link, useNavigate } from '@tanstack/react-router'
import { registerPublic } from '@/lib/taiga/client'
import { Skeleton } from '@/components/ui/skeleton'
import { AuthLayout } from '../auth-layout'
import { AccountForm } from './account-form'
import { useRegistrationOpen } from './use-registration-open'

export function SignUp() {
  const navigate = useNavigate()
  const open = useRegistrationOpen()
  return (
    <AuthLayout
      title='Create an account'
      description={
        <>
          Already have one?{' '}
          <Link
            to='/sign-in'
            className='text-foreground underline underline-offset-4'
          >
            Sign in
          </Link>
        </>
      }
    >
      {open.isPending ? (
        <Skeleton className='h-64 w-full' />
      ) : open.data ? (
        <AccountForm
          submitLabel='Create account'
          onSubmit={async (account) => {
            await registerPublic(account)
            navigate({ to: '/', replace: true })
          }}
        />
      ) : (
        <p className='text-sm text-muted-foreground'>
          This server does not take new sign-ups. Ask a project admin to invite
          you; the invitation email has a link to create your account.
        </p>
      )}
    </AuthLayout>
  )
}
