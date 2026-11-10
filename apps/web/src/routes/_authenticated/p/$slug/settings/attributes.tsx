import { createFileRoute } from '@tanstack/react-router'
import { AttributesSettings } from '@/features/project-settings/attributes'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/settings/attributes'
)({
  component: AttributesSettings,
})
