import { createFileRoute } from '@tanstack/react-router'
import { MembersSettings } from '@/features/project-settings/members'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/settings/members'
)({
  component: MembersSettings,
})
