import { z } from 'zod'
import { createFileRoute, redirect } from '@tanstack/react-router'
import { useAuthStore } from '@/stores/auth-store'
import { safeRedirect } from '@/lib/utils'
import { SignIn } from '@/features/auth/sign-in'

const searchSchema = z.object({
  redirect: z.string().optional(),
})

export const Route = createFileRoute('/(auth)/sign-in')({
  validateSearch: searchSchema,
  // Already signed in (e.g. following an email link): go straight on.
  beforeLoad: ({ search }) => {
    if (useAuthStore.getState().session)
      throw redirect({ to: safeRedirect(search.redirect), replace: true })
  },
  component: SignIn,
})
