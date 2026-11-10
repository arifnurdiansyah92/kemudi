import { createFileRoute } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { TokenAction } from '@/features/auth/token-action'

/** Link from the 'delete your account' message. */
export const Route = createFileRoute('/(auth)/cancel-account/$token')({
  component: function CancelAccount() {
    const { t } = useTranslation('shell')
    const { token } = Route.useParams()
    return (
      <TokenAction
        title={t('tokenLinks.cancelAccount.title')}
        endpoint='/users/cancel'
        body={{ cancel_token: token }}
        done={t('tokenLinks.cancelAccount.done')}
        failed={t('tokenLinks.cancelAccount.failed')}
        confirm={{
          label: t('tokenLinks.cancelAccount.confirm'),
          text: t('tokenLinks.cancelAccount.confirmText'),
        }}
      />
    )
  },
})
