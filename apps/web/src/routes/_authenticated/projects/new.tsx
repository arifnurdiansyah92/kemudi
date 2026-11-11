import { createFileRoute } from '@tanstack/react-router'
import { NewProject } from '@/features/projects/new-project'

export const Route = createFileRoute('/_authenticated/projects/new')({
  component: NewProject,
})
