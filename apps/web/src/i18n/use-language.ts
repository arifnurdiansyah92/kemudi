import { useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/stores/auth-store'
import { api } from '@/lib/taiga/client'
import type { AuthUser } from '@/lib/taiga/types'
import {
  currentLanguage,
  setLanguage,
  toLanguage,
  type Language,
} from './index'

/**
 * Follow the signed-in user's Taiga language, so one choice covers every
 * device and the emails kemudi-back sends. A user whose `lang` is empty or
 * one we don't ship keeps this device's choice.
 */
export function useLanguageSync() {
  const lang = useAuthStore((s) => s.session?.user.lang)
  useEffect(() => {
    const lng = toLanguage(lang)
    if (lng) setLanguage(lng)
  }, [lang])
}

/** The current language and a setter that also saves it to the user. */
export function useLanguage() {
  useTranslation()
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: async (lng: Language) => {
      const user = useAuthStore.getState().session?.user
      if (!user) return null
      return (await api.patch<AuthUser>(`/users/${user.id}`, { lang: lng }))
        .data
    },
    onSuccess: (user) => {
      if (user) useAuthStore.getState().setUser(user)
      qc.invalidateQueries({ queryKey: ['me'] })
    },
  })
  return {
    language: currentLanguage(),
    setLanguage: (lng: Language) => {
      setLanguage(lng)
      save.mutate(lng)
    },
  }
}
