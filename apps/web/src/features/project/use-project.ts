import { useSuspenseQuery } from '@tanstack/react-query'
import { useNavigate, useParams, useSearch } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import type { Project } from '@/lib/taiga/types'

/** The project of the current /p/$slug route. Its loader has already fetched it. */
export function useProject(): Project {
  const { slug } = useParams({ from: '/_authenticated/p/$slug' })
  return useSuspenseQuery(projectQuery(slug)).data
}

export function can(project: Project, permission: string) {
  return project.my_permissions.includes(permission)
}

/** Opens and closes the story side sheet through the `?story=` search param. */
export function useStoryParam() {
  const { story } = useSearch({ from: '/_authenticated/p/$slug' })
  const navigate = useNavigate()
  return {
    openRef: story,
    open: (ref: number) =>
      navigate({
        to: '.',
        search: (prev: Record<string, unknown>) => ({ ...prev, story: ref }),
      }),
    close: () =>
      navigate({
        to: '.',
        search: (prev: Record<string, unknown>) => ({
          ...prev,
          story: undefined,
        }),
      }),
  }
}
