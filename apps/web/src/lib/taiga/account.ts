/** The signed-in user's own account: profile, password, email, notifications. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth-store'
import { api, apiErrorMessage } from './client'
import { onFail } from './items'
import type { AuthUser, Id } from './types'

export interface Me extends AuthUser {
  bio: string
  theme: string
  verified_email: boolean
  date_joined: string
}

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const { data } = await api.get<Me>('/users/me')
      // Keep the sidebar's name and photo in step with the profile.
      useAuthStore.getState().setUser(data)
      return data
    },
  })
}

function useSettle() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['me'] })
    // Names and photos also appear in project member lists.
    qc.invalidateQueries({ queryKey: ['project'] })
  }
}

export function useUpdateMe() {
  const settle = useSettle()
  return useMutation({
    mutationFn: async (patch: Partial<Me>) => {
      const me = useAuthStore.getState().session!.user
      return (await api.patch<Me>(`/users/${me.id}`, patch)).data
    },
    onSuccess: (_d, patch) =>
      toast.success(
        'email' in patch
          ? 'Check your new address for a link to confirm the change.'
          : 'Profile saved'
      ),
    onError: onFail,
    onSettled: settle,
  })
}

export function useAvatar() {
  const settle = useSettle()
  const change = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('avatar', file)
      return api.post('/users/change_avatar', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onError: (e) =>
      toast.error(apiErrorMessage(e, 'That image could not be used.')),
    onSettled: settle,
  })
  const remove = useMutation({
    mutationFn: () => api.post('/users/remove_avatar'),
    onError: onFail,
    onSettled: settle,
  })
  return { change, remove }
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (input: { current_password: string; password: string }) =>
      api.post('/users/change_password', input),
    onSuccess: () => toast.success('Password changed'),
    onError: onFail,
  })
}

/** Deactivates the account; kemudi-back keeps the user's work, anonymised. */
export function useDeleteAccount() {
  return useMutation({
    mutationFn: () => {
      const me = useAuthStore.getState().session!.user
      return api.delete(`/users/${me.id}`)
    },
    onError: onFail,
  })
}

export interface NotifyPolicy {
  id: Id
  project: Id
  project_name: string
  /** 1 all activity, 2 only items I'm involved in, 3 none. */
  notify_level: 1 | 2 | 3
  live_notify_level: 1 | 2 | 3
  web_notify_level: boolean
}

export function useNotifyPolicies() {
  return useQuery({
    queryKey: ['notify-policies'],
    queryFn: async () =>
      (await api.get<NotifyPolicy[]>('/notify-policies')).data,
  })
}

export function useUpdateNotifyPolicy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      policy,
      patch,
    }: {
      policy: NotifyPolicy
      patch: Partial<NotifyPolicy>
    }) => api.patch(`/notify-policies/${policy.id}`, patch),
    onMutate: ({ policy, patch }) =>
      qc.setQueryData<NotifyPolicy[]>(['notify-policies'], (list) =>
        list?.map((p) => (p.id === policy.id ? { ...p, ...patch } : p))
      ),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['notify-policies'] }),
  })
}

export interface Locale {
  code: string
  name: string
  bidi: boolean
}

export function useLocales() {
  return useQuery({
    queryKey: ['locales'],
    staleTime: Infinity,
    queryFn: async () => (await api.get<Locale[]>('/locales')).data,
  })
}

export interface ApplicationToken {
  id: Id
  application: {
    id: string
    name: string
    web: string
    description: string
    icon_url: string | null
  }
}

export function useApplicationTokens() {
  const qc = useQueryClient()
  const list = useQuery({
    queryKey: ['application-tokens'],
    queryFn: async () =>
      (await api.get<ApplicationToken[]>('/application-tokens')).data,
  })
  const revoke = useMutation({
    mutationFn: (t: ApplicationToken) =>
      api.delete(`/application-tokens/${t.id}`),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['application-tokens'] }),
  })
  return { list, revoke }
}
