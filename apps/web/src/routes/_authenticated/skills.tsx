import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { SkillsPage } from '@/features/skills'

const searchSchema = z.object({
  tab: z.enum(['installed', 'create']).optional().catch(undefined),
  skill: z.string().optional(),
  edit: z.string().optional(),
})

export const Route = createFileRoute('/_authenticated/skills')({
  validateSearch: searchSchema,
  component: function SkillsRoute() {
    const search = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
      <SkillsPage
        search={search}
        navigate={(next) => navigate({ search: next })}
      />
    )
  },
})
