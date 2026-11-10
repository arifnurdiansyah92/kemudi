import { z } from 'zod'
import { createFileRoute, Outlet } from '@tanstack/react-router'
import { projectQuery } from '@/lib/taiga/queries'
import { ItemSheet } from '@/features/item/item-sheet'
import { ProjectError } from '@/features/project/project-error'

const searchSchema = z.object({
  /** Ref of the story, task, issue or epic open in the side sheet. */
  ref: z.coerce.number().int().positive().optional(),
})

export const Route = createFileRoute('/_authenticated/p/$slug')({
  validateSearch: searchSchema,
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(projectQuery(params.slug)),
  errorComponent: ProjectError,
  component: () => (
    <>
      <Outlet />
      <ItemSheet />
    </>
  ),
})
