import { createFileRoute } from '@tanstack/react-router'
import { ProjectSettingsLayout } from '@/features/project-settings/layout'

export const Route = createFileRoute('/_authenticated/p/$slug/settings')({
  component: ProjectSettingsLayout,
})
