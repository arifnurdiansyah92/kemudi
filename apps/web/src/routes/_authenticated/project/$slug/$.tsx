import { createFileRoute, redirect } from '@tanstack/react-router'
import { resolveLegacyProjectPath } from '@/lib/legacy-urls'

/** Old taiga-front project URLs (emails, rendered Markdown) → Kemudi. */
export const Route = createFileRoute('/_authenticated/project/$slug/$')({
  beforeLoad: async ({ params }) => {
    const target = await resolveLegacyProjectPath(
      params.slug,
      params._splat ?? ''
    )
    throw redirect({ ...(target as object), replace: true } as never)
  },
})
