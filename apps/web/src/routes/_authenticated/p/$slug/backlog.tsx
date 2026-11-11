import { createFileRoute, redirect } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import { Backlog } from '@/features/backlog'

export const Route = createFileRoute('/_authenticated/p/$slug/backlog')({
  // Respect the project's module settings, as the sidebar does.
  beforeLoad: async ({ context, params }) => {
    const project = await context.queryClient.ensureQueryData(
      projectQuery(params.slug)
    )
    if (!project.is_backlog_activated && project.is_kanban_activated)
      throw redirect({ to: '/p/$slug/kanban', params, replace: true })
  },
  component: Backlog,
})
