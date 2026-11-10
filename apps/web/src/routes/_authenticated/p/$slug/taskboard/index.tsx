import { format } from 'date-fns'
import { createFileRoute, redirect } from '@tanstack/react-router'
import { api } from '@/lib/taiga/client'
import { projectQuery } from '@/lib/taiga/queries'
import type { Milestone } from '@/lib/taiga/types'
import { NoSprint } from '@/features/taskboard/no-sprint'

/** Opens the sprint running today, else the next one, else the latest. */
export const Route = createFileRoute('/_authenticated/p/$slug/taskboard/')({
  beforeLoad: async ({ context, params }) => {
    const project = await context.queryClient.ensureQueryData(
      projectQuery(params.slug)
    )
    const { data: sprints } = await api.get<Milestone[]>('/milestones', {
      params: { project: project.id, closed: false },
      headers: { 'x-disable-pagination': '1' },
    })
    const today = format(new Date(), 'yyyy-MM-dd')
    const sorted = [...sprints].sort((a, b) =>
      a.estimated_start.localeCompare(b.estimated_start)
    )
    const pick =
      sorted.find(
        (s) => s.estimated_start <= today && today <= s.estimated_finish
      ) ??
      sorted.find((s) => s.estimated_start > today) ??
      sorted[sorted.length - 1]
    if (pick)
      throw redirect({
        to: '/p/$slug/taskboard/$sprint',
        params: { slug: params.slug, sprint: String(pick.id) },
        replace: true,
      })
  },
  component: NoSprint,
})
