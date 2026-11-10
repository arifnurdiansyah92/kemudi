import { z } from 'zod'
import { createFileRoute, redirect } from '@tanstack/react-router'

/** taiga-front's /login?next=… → /sign-in?redirect=… */
export const Route = createFileRoute('/(auth)/login')({
  validateSearch: z.object({ next: z.string().optional() }),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: '/sign-in',
      search: { redirect: search.next },
      replace: true,
    })
  },
})
