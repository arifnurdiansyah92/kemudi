import { AxiosError } from 'axios'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/taiga/client'

export type Service = 'jira' | 'trello' | 'github' | 'asana'

export const SERVICES: Record<Service, { name: string; env: string }> = {
  jira: { name: 'Jira', env: 'ENABLE_JIRA_IMPORTER' },
  trello: { name: 'Trello', env: 'ENABLE_TRELLO_IMPORTER' },
  github: { name: 'GitHub', env: 'ENABLE_GITHUB_IMPORTER' },
  asana: { name: 'Asana', env: 'ENABLE_ASANA_IMPORTER' },
}

const tokenKey = (s: Service) => `kemudi.import.${s}`

export function readToken(s: Service) {
  try {
    return sessionStorage.getItem(tokenKey(s))
  } catch {
    return null
  }
}

export function saveToken(s: Service, token: string | null) {
  try {
    if (token) sessionStorage.setItem(tokenKey(s), token)
    else sessionStorage.removeItem(tokenKey(s))
  } catch {
    // Storage unavailable: the token lives for this page only.
  }
}

/** Where the service sends the browser back after sign-in. */
export function callbackUrl(s: Service) {
  return `${window.location.origin}/projects/import/${s}`
}

/**
 * kemudi-back registers an importer's endpoints only when an administrator
 * configured it, so a 404 on auth_url means "not set up on this server".
 */
export function useImporterAvailable(
  service: Service,
  jiraUrl = 'https://example.atlassian.net'
) {
  return useQuery({
    queryKey: ['importer-available', service, jiraUrl],
    staleTime: Infinity,
    retry: false,
    queryFn: async () => {
      try {
        await api.get(`/importers/${service}/auth_url`, {
          params:
            service === 'jira'
              ? { url: jiraUrl }
              : service === 'github'
                ? { uri: callbackUrl(service) }
                : {},
        })
        return true
      } catch (e) {
        return !(e instanceof AxiosError && e.response?.status === 404)
      }
    },
  })
}
