import { createFileRoute } from '@tanstack/react-router'
import { Contract } from '@/features/contract'

export const Route = createFileRoute('/_authenticated/p/$slug/contract')({
  component: Contract,
})
