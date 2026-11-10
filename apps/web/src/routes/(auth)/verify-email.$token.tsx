import { createFileRoute } from '@tanstack/react-router'
import { TokenAction } from '@/features/auth/token-action'

/** Link from the 'verify your email' message. */
export const Route = createFileRoute('/(auth)/verify-email/$token')({
  component: function VerifyEmail() {
    const { token } = Route.useParams()
    return (
      <TokenAction
        title='Confirm your email'
        endpoint='/users/change_email'
        body={{ email_token: token }}
        done='Your email address is confirmed.'
        failed='This link is invalid or was already used.'
      />
    )
  },
})
