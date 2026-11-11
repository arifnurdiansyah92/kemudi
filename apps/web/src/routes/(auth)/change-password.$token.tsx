import { createFileRoute } from '@tanstack/react-router'
import { ChangePassword } from '@/features/auth/change-password'

export const Route = createFileRoute('/(auth)/change-password/$token')({
  component: ChangePassword,
})
