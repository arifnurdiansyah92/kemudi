import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/_authenticated/project/$slug/')({
  beforeLoad: ({ params }) => {
    throw redirect({ to: '/p/$slug', params, replace: true })
  },
})
