import { createFileRoute } from '@tanstack/react-router'
import { InvitationPage } from '@/features/auth/invitation'

export const Route = createFileRoute('/(auth)/invitation/$token')({
  component: function Invitation() {
    const { token } = Route.useParams()
    return <InvitationPage token={token} />
  },
})
