import { createFileRoute } from '@tanstack/react-router'
import { GeneralSettings } from '@/features/project-settings/general'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/settings/general'
)({
  component: GeneralSettings,
})
