import { createFileRoute, redirect } from '@tanstack/react-router'

/** taiga-front's importer return address → Kemudi's, keeping the query. */
export const Route = createFileRoute(
  '/_authenticated/project/new/import/$service'
)({
  validateSearch: (search: Record<string, unknown>) => search,
  beforeLoad: ({ params, search }) => {
    throw redirect({
      to: '/projects/import/$service',
      params: { service: params.service },
      search: search as never,
      replace: true,
    })
  },
})
