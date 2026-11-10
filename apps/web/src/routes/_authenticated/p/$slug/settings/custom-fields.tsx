import { createFileRoute } from '@tanstack/react-router'
import { CustomFieldsSettings } from '@/features/project-settings/custom-fields'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/settings/custom-fields'
)({
  component: CustomFieldsSettings,
})
