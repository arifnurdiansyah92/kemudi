import { createFileRoute } from '@tanstack/react-router'
import { AgentSettingsPage } from '@/features/agent-settings'

export const Route = createFileRoute('/_authenticated/p/$slug/settings/agent')({
  component: AgentSettingsPage,
})
