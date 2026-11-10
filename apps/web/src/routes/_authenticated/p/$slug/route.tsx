import { z } from 'zod'
import { createFileRoute, Outlet } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import { ProjectError } from '@/features/project/project-error'
import { StorySheet } from '@/features/story/story-sheet'

const searchSchema = z.object({
  /** Ref of the story open in the side sheet. */
  story: z.coerce.number().int().positive().optional(),
})

export const Route = createFileRoute('/_authenticated/p/$slug')({
  validateSearch: searchSchema,
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(projectQuery(params.slug)),
  errorComponent: ProjectError,
  component: () => (
    <>
      <Outlet />
      <StorySheet />
    </>
  ),
})
