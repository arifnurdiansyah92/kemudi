import { createFileRoute } from '@tanstack/react-router'
import { PortfolioPage } from '@/features/portfolio'

export const Route = createFileRoute('/_authenticated/portfolio')({
  component: PortfolioPage,
})
