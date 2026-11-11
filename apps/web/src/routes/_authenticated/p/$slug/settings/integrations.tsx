import { createFileRoute } from '@tanstack/react-router'
import { IntegrationsSettings } from '@/features/project-settings/integrations'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/settings/integrations'
)({
  component: IntegrationsSettings,
})
