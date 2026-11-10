import { createFileRoute } from '@tanstack/react-router'
import { RolesSettings } from '@/features/project-settings/roles'

export const Route = createFileRoute('/_authenticated/p/$slug/settings/roles')({
  component: RolesSettings,
})
