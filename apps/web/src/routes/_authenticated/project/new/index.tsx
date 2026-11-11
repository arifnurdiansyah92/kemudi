import { createFileRoute, redirect } from '@tanstack/react-router'

/** taiga-front's /project/new (and /project/new/import/...) → /projects/new. */
export const Route = createFileRoute('/_authenticated/project/new/')({
  beforeLoad: () => {
    throw redirect({ to: '/projects/new', replace: true })
  },
})
