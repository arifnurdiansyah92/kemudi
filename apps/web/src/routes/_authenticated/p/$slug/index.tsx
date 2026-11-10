import { createFileRoute, redirect } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'

/** A project opens on its backlog, or on kanban when the backlog is off. */
export const Route = createFileRoute('/_authenticated/p/$slug/')({
  beforeLoad: async ({ context, params }) => {
    const project = await context.queryClient.ensureQueryData(
      projectQuery(params.slug)
    )
    throw redirect({
      to:
        !project.is_backlog_activated && project.is_kanban_activated
          ? '/p/$slug/kanban'
          : '/p/$slug/backlog',
      params,
      replace: true,
    })
  },
})
