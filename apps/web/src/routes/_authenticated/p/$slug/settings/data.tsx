import { createFileRoute } from '@tanstack/react-router'
import { DataSettings } from '@/features/project-settings/data'

export const Route = createFileRoute('/_authenticated/p/$slug/settings/data')({
  component: DataSettings,
})
