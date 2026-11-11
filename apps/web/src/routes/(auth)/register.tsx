import { createFileRoute, redirect } from '@tanstack/react-router'

/** taiga-front's /register → /sign-up. */
export const Route = createFileRoute('/(auth)/register')({
  beforeLoad: () => {
    throw redirect({ to: '/sign-up', replace: true })
  },
})
