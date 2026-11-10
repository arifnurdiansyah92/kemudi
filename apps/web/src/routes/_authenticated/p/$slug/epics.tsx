import { createFileRoute, redirect } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import { Epics } from '@/features/epics'

export const Route = createFileRoute('/_authenticated/p/$slug/epics')({
  beforeLoad: async ({ context, params }) => {
    const project = await context.queryClient.ensureQueryData(
      projectQuery(params.slug)
    )
    if (!project.is_epics_activated)
      throw redirect({ to: '/p/$slug', params, replace: true })
  },
  component: Epics,
})
