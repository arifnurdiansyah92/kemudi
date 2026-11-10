import { createFileRoute } from '@tanstack/react-router'
import { Profile } from '@/features/profile'

export const Route = createFileRoute('/_authenticated/profile/$username')({
  component: function ProfileRoute() {
    const { username } = Route.useParams()
    return <Profile key={username} username={username} />
  },
})
