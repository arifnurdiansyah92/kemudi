import { createFileRoute } from '@tanstack/react-router'
import { ProfileSettings } from '@/features/settings/account-pages'

export const Route = createFileRoute('/_authenticated/settings/profile')({
  component: ProfileSettings,
})
