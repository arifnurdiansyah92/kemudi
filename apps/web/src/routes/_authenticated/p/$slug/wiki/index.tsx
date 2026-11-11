import { createFileRoute, redirect } from '@tanstack/react-router'

/** The wiki opens on its home page, as in Taiga. */
export const Route = createFileRoute('/_authenticated/p/$slug/wiki/')({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: '/p/$slug/wiki/$page',
      params: { slug: params.slug, page: 'home' },
      replace: true,
    })
  },
})
