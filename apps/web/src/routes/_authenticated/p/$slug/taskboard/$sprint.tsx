import { createFileRoute } from '@tanstack/react-router'
import { Taskboard } from '@/features/taskboard'

export const Route = createFileRoute(
  '/_authenticated/p/$slug/taskboard/$sprint'
)({
  component: function TaskboardRoute() {
    const { sprint } = Route.useParams()
    return <Taskboard key={sprint} sprintId={Number(sprint)} />
  },
})
