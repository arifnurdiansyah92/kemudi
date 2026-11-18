import { z } from 'zod'
import { createFileRoute } from '@tanstack/react-router'
import { Research } from '@/features/research'

const searchSchema = z.object({
  /** Id of the run whose report is open, so a link opens that report. */
  run: z.coerce.number().int().positive().optional().catch(undefined),
})

export const Route = createFileRoute('/_authenticated/p/$slug/research')({
  validateSearch: searchSchema,
  component: Research,
})
