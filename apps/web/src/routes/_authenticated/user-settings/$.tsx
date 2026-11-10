import { createFileRoute, redirect } from '@tanstack/react-router'

/** taiga-front's /user-settings/... → /settings/... */
export const Route = createFileRoute('/_authenticated/user-settings/$')({
  beforeLoad: ({ params }) => {
    const to = params._splat?.startsWith('mail-notifications')
      ? '/settings/notifications'
      : params._splat?.startsWith('user-change-password')
        ? '/settings/account'
        : '/settings/profile'
    throw redirect({ to, replace: true })
  },
})
