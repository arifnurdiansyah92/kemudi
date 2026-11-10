import { createFileRoute } from '@tanstack/react-router'
import { AppsSettings } from '@/features/settings/account-pages'

export const Route = createFileRoute('/_authenticated/settings/apps')({
  component: AppsSettings,
})
