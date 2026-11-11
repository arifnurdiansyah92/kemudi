import { createFileRoute } from '@tanstack/react-router'
import { SprintAccessSettings } from '@/features/project-settings/sprint-access'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/settings/sprint-access'
)({
  component: SprintAccessSettings,
})
