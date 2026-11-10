import { z } from 'zod'
import { createFileRoute, redirect } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import { Wiki } from '@/features/wiki'

export const Route = createFileRoute('/_authenticated/p/$slug/wiki/$page')({
  validateSearch: z.object({ edit: z.boolean().optional() }),
  beforeLoad: async ({ context, params }) => {
    const project = await context.queryClient.ensureQueryData(
      projectQuery(params.slug)
    )
    if (!project.is_wiki_activated)
      throw redirect({
        to: '/p/$slug',
        params: { slug: params.slug },
        replace: true,
      })
  },
  component: function WikiRoute() {
    const { page } = Route.useParams()
    const { edit } = Route.useSearch()
    return <Wiki key={page} slug={page} edit={edit} />
  },
})
