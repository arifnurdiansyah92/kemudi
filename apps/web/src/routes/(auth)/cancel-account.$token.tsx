import { createFileRoute } from '@tanstack/react-router'
import { TokenAction } from '@/features/auth/token-action'

/** Link from the 'delete your account' message. */
export const Route = createFileRoute('/(auth)/cancel-account/$token')({
  component: function CancelAccount() {
    const { token } = Route.useParams()
    return (
      <TokenAction
        title='Delete your account'
        endpoint='/users/cancel'
        body={{ cancel_token: token }}
        done='Your account is deleted.'
        failed='This link is invalid or has expired.'
        confirm={{
          label: 'Delete my account',
          text: 'You will be removed from every project and cannot sign in again. Your past work stays, without your name.',
        }}
      />
    )
  },
})
