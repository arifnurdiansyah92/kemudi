import { createFileRoute } from '@tanstack/react-router'
import { Discover } from '@/features/projects/discover'

export const Route = createFileRoute('/_authenticated/discover')({
  component: Discover,
})
