import { createFileRoute, redirect } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import { Kanban } from '@/features/kanban'

export const Route = createFileRoute('/_authenticated/p/$slug/kanban')({
  // Respect the project's module settings, as the sidebar does.
  beforeLoad: async ({ context, params }) => {
    const project = await context.queryClient.ensureQueryData(
      projectQuery(params.slug)
    )
    if (!project.is_kanban_activated)
      throw redirect({ to: '/p/$slug/backlog', params, replace: true })
  },
  component: Kanban,
})
