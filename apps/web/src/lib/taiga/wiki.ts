/** Wiki pages, their bookmarks (wiki links), and Markdown preview. */
import { AxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from './client'
import { onFail } from './items'
import type { Id, Project } from './types'

const ALL = { headers: { 'x-disable-pagination': '1' } }

export interface WikiPage {
  id: Id
  slug: string
  content: string
  html: string
  version: number
  editions: number
  owner: Id
  last_modifier: Id
  created_date: string
  modified_date: string
  is_watcher: boolean
  total_watchers: number
}

interface WikiLink {
  id: Id
  title: string
  href: string
  order: number
}

export function useWikiPages(projectId: Id) {
  return useQuery({
    queryKey: ['wiki', projectId],
    queryFn: async () =>
      (
        await api.get<WikiPage[]>('/wiki', {
          params: { project: projectId },
          ...ALL,
        })
      ).data.sort((a, b) => a.slug.localeCompare(b.slug)),
  })
}

/** The page, or null when no page has that slug yet. */
export function useWikiPage(projectId: Id, slug: string) {
  return useQuery({
    queryKey: ['wiki', projectId, slug],
    queryFn: async () => {
      try {
        return (
          await api.get<WikiPage>('/wiki/by_slug', {
            params: { project: projectId, slug },
          })
        ).data
      } catch (error) {
        if (error instanceof AxiosError && error.response?.status === 404)
          return null
        throw error
      }
    },
  })
}

/** Creates the page on first save, then updates it. */
export function useSaveWikiPage(project: Project, slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({
      page,
      content,
    }: {
      page: WikiPage | null
      content: string
    }) =>
      page
        ? (
            await api.patch<WikiPage>(`/wiki/${page.id}`, {
              content,
              version: page.version,
            })
          ).data
        : (
            await api.post<WikiPage>('/wiki', {
              project: project.id,
              slug,
              content,
            })
          ).data,
    onSuccess: (page) => {
      qc.setQueryData(['wiki', project.id, slug], page)
      qc.invalidateQueries({ queryKey: ['wiki', project.id], exact: true })
    },
    onError: onFail,
  })
}

export function useDeleteWikiPage(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (page: WikiPage) => api.delete(`/wiki/${page.id}`),
    onSuccess: (_d, page) => {
      toast.success(`Page "${page.slug}" deleted`)
      qc.setQueryData(['wiki', project.id, page.slug], null)
    },
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['wiki', project.id] }),
  })
}

export function useWatchWikiPage(project: Project) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (page: WikiPage) =>
      api.post(`/wiki/${page.id}/${page.is_watcher ? 'unwatch' : 'watch'}`),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['wiki', project.id] }),
  })
}

export function useRenderMarkdown(project: Project) {
  return useMutation({
    mutationFn: async (content: string) =>
      (
        await api.post<{ data: string }>('/wiki/render', {
          project_id: project.id,
          content,
        })
      ).data.data,
  })
}

export function useWikiLinks(projectId: Id) {
  return useQuery({
    queryKey: ['wiki-links', projectId],
    queryFn: async () =>
      (
        await api.get<WikiLink[]>('/wiki-links', {
          params: { project: projectId },
          ...ALL,
        })
      ).data.sort((a, b) => a.order - b.order),
  })
}

export function useWikiLinkMutations(project: Project) {
  const qc = useQueryClient()
  const settle = () =>
    qc.invalidateQueries({ queryKey: ['wiki-links', project.id] })
  const add = useMutation({
    mutationFn: (input: { title: string; href: string }) =>
      api.post('/wiki-links', { project: project.id, ...input }),
    onError: onFail,
    onSettled: settle,
  })
  const remove = useMutation({
    mutationFn: (link: WikiLink) => api.delete(`/wiki-links/${link.id}`),
    onError: onFail,
    onSettled: settle,
  })
  return { add, remove }
}

/** "getting-started" → "Getting started". */
export function pageTitle(slug: string) {
  const words = slug.replace(/[-_]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** "Getting Started!" → "getting-started", as Taiga slugifies. */
export function slugify(text: string) {
  return text
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
