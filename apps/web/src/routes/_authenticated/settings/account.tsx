import { createFileRoute } from '@tanstack/react-router'
import { AccountSettings } from '@/features/settings/account-pages'

export const Route = createFileRoute('/_authenticated/settings/account')({
  component: AccountSettings,
})
