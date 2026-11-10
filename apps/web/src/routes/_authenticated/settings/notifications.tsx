import { createFileRoute } from '@tanstack/react-router'
import { NotificationSettings } from '@/features/settings/account-pages'

export const Route = createFileRoute('/_authenticated/settings/notifications')({
  component: NotificationSettings,
})
