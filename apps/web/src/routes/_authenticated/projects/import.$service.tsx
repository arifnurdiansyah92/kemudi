import { z } from 'zod'
import { createFileRoute, notFound } from '@tanstack/react-router'
import { Importer } from '@/features/importers'
import { SERVICES, type Service } from '@/features/importers/services'

/** Also the OAuth return address: the service adds code or oauth_verifier. */
const searchSchema = z.object({
  code: z.string().optional(),
  oauth_verifier: z.string().optional(),
  oauth_token: z.string().optional(),
  url: z.string().optional(),
})

export const Route = createFileRoute(
  '/_authenticated/projects/import/$service'
)({
  validateSearch: searchSchema,
  beforeLoad: ({ params }) => {
    if (!(params.service in SERVICES)) throw notFound()
  },
  component: function ImportRoute() {
    const { service } = Route.useParams()
    const search = Route.useSearch()
    return (
      <Importer key={service} service={service as Service} callback={search} />
    )
  },
})
