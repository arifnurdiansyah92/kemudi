import { createFileRoute } from '@tanstack/react-router'
import { Intake } from '@/features/intake'

export const Route = createFileRoute('/_authenticated/p/$slug/intake')({
  component: Intake,
})
