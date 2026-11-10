import { createFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { TokenAction } from '@/features/auth/token-action'

/** Link from the 'verify your email' message. */
export const Route = createFileRoute('/(auth)/verify-email/$token')({
  component: function VerifyEmail() {
    const { t } = useTranslation('shell')
    const { token } = Route.useParams()
    return (
      <TokenAction
        title={t('tokenLinks.email.title')}
        endpoint='/users/change_email'
        body={{ email_token: token }}
        done={t('tokenLinks.email.done')}
        failed={t('tokenLinks.email.failed')}
      />
    )
  },
})
