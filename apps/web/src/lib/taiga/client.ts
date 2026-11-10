import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/auth-store'
import type { AuthResponse } from './types'

/**
 * Axios instance for kemudi-back. In development Vite proxies `/api` to the
 * dev gateway; in the container the gateway serves both from one origin.
 */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

const isAuthCall = (url?: string) => !!url?.startsWith('/auth')

api.interceptors.request.use((config) => {
  // Sign-in and refresh must not carry a (possibly expired) bearer token:
  // taiga-back rejects the request outright when the token is invalid.
  const token = useAuthStore.getState().session?.token
  if (token && !isAuthCall(config.url))
    config.headers.Authorization = `Bearer ${token}`
  return config
})

let refreshing: Promise<string> | null = null

async function refreshToken(): Promise<string> {
  const { session, setTokens } = useAuthStore.getState()
  if (!session?.refresh) throw new Error('No refresh token')
  const { data } = await api.post<{ auth_token: string; refresh: string }>(
    '/auth/refresh',
    { refresh: session.refresh }
  )
  setTokens(data.auth_token, data.refresh)
  return data.auth_token
}

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

api.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as RetriableConfig | undefined
  if (
    error.response?.status === 401 &&
    config &&
    !config._retried &&
    !isAuthCall(config.url) &&
    useAuthStore.getState().session?.refresh
  ) {
    config._retried = true
    try {
      refreshing ??= refreshToken().finally(() => {
        refreshing = null
      })
      const token = await refreshing
      config.headers.Authorization = `Bearer ${token}`
      return api(config)
    } catch {
      useAuthStore.getState().reset()
    }
  }
  return Promise.reject(error)
})

export async function signIn(username: string, password: string) {
  const { data } = await api.post<AuthResponse>('/auth', {
    type: 'normal',
    username,
    password,
  })
  const { auth_token, refresh, ...user } = data
  useAuthStore.getState().setSession({ token: auth_token, refresh, user })
  return user
}

export async function requestPasswordReset(username: string) {
  await api.post('/users/password_recovery', { username })
}

/** Reads the first human-readable message out of a Taiga error body. */
export function apiErrorMessage(
  error: unknown,
  fallback = 'Something went wrong.'
) {
  if (!(error instanceof AxiosError)) return fallback
  const data = error.response?.data as Record<string, unknown> | undefined
  if (!data) return error.message || fallback
  if (typeof data._error_message === 'string') return data._error_message
  for (const [field, value] of Object.entries(data)) {
    const message =
      typeof value === 'string'
        ? value
        : Array.isArray(value) && typeof value[0] === 'string'
          ? value[0]
          : null
    if (!message) continue
    // Name the field, so "Invalid value." says which one.
    if (field === 'non_field_errors' || field === 'detail') return message
    const label = field.replace(/_/g, ' ')
    const name = label.length <= 3 ? label.toUpperCase() : label[0].toUpperCase() + label.slice(1)
    return `${name}: ${message}`
  }
  return fallback
}

/**
 * Avatar URL: the uploaded photo only. No Gravatar fallback, so a
 * self-hosted install never sends hashed emails to a third party.
 */
export function avatarUrl(user: { photo: string | null }) {
  return user.photo ?? undefined
}

export function initials(name: string) {
  return name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}
