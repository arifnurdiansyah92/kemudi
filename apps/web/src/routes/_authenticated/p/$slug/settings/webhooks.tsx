import { createFileRoute } from '@tanstack/react-router'
import { WebhooksSettings } from '@/features/project-settings/webhooks'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/settings/webhooks'
)({
  component: WebhooksSettings,
})
