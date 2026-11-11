import { createFileRoute } from '@tanstack/react-router'
import { TagsSettings } from '@/features/project-settings/tags'

export const Route = createFileRoute('/_authenticated/p/$slug/settings/tags')({
  component: TagsSettings,
})
