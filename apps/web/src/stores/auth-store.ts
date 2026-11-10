import { create } from 'zustand'
import type { AuthUser } from '@/lib/taiga/types'

const STORAGE_KEY = 'kemudi.auth'

interface Session {
  token: string
  refresh: string
  user: AuthUser
}

interface AuthState {
  session: Session | null
  setSession: (session: Session) => void
  setTokens: (token: string, refresh: string) => void
  setUser: (user: AuthUser) => void
  reset: () => void
}

function load(): Session | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Session
    return parsed.token && parsed.user ? parsed : null
  } catch {
    return null
  }
}

function save(session: Session | null) {
  try {
    if (session) localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage unavailable (private mode): the session lives in memory only.
  }
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  session: load(),
  setSession: (session) => {
    save(session)
    set({ session })
  },
  setTokens: (token, refresh) => {
    const current = get().session
    if (!current) return
    const session = { ...current, token, refresh }
    save(session)
    set({ session })
  },
  setUser: (user) => {
    const current = get().session
    if (!current) return
    const session = { ...current, user }
    save(session)
    set({ session })
  },
  reset: () => {
    save(null)
    set({ session: null })
  },
}))
