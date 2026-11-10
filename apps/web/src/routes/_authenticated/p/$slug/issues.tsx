import { createFileRoute, redirect } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import { Issues } from '@/features/issues'

export const Route = createFileRoute('/_authenticated/p/$slug/issues')({
  beforeLoad: async ({ context, params }) => {
    const project = await context.queryClient.ensureQueryData(
      projectQuery(params.slug)
    )
    if (!project.is_issues_activated)
      throw redirect({ to: '/p/$slug', params, replace: true })
  },
  component: Issues,
})
