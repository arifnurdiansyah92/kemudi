/**
 * kemudi-back still writes taiga-front URLs: in rendered Markdown (wiki
 * links, #ref mentions) and in notification emails. See
 * services/kemudi-back/taiga/front/urls.py. This maps them to Kemudi routes.
 */
import { api } from './taiga/client'
import type { ResolvedRef } from './taiga/types'

type Target = {
  to: string
  params?: Record<string, string>
  search?: Record<string, unknown>
}

/** `rest` is the path after /project/<slug>/, e.g. "us/14" or "wiki/home". */
export async function resolveLegacyProjectPath(
  slug: string,
  rest: string
): Promise<Target> {
  const [section, arg] = rest.split('/').filter(Boolean)
  const params = { slug }
  const item = (page: string) => ({
    to: `/p/$slug/${page}`,
    params,
    search: { ref: Number(arg) },
  })
  switch (section) {
    case 'us':
    case 'task':
      return item('backlog')
    case 'issue':
      return item('issues')
    case 'epic':
      return item('epics')
    case 'backlog':
    case 'kanban':
    case 'issues':
    case 'epics':
    case 'team':
    case 'timeline':
      return { to: `/p/$slug/${section}`, params }
    case 'wiki':
      return arg
        ? { to: '/p/$slug/wiki/$page', params: { slug, page: arg } }
        : { to: '/p/$slug/wiki', params }
    case 'taskboard': {
      if (!arg) return { to: '/p/$slug/taskboard', params }
      try {
        const { data } = await api.get<ResolvedRef & { milestone?: number }>(
          '/resolver',
          { params: { project: slug, milestone: arg } }
        )
        if (data.milestone)
          return {
            to: '/p/$slug/taskboard/$sprint',
            params: { slug, sprint: String(data.milestone) },
          }
      } catch {
        // Unknown sprint: fall through to the current one.
      }
      return { to: '/p/$slug/taskboard', params }
    }
    case 'transfer':
      return arg
        ? { to: '/p/$slug/transfer/$token', params: { slug, token: arg } }
        : { to: '/p/$slug', params }
    case 'admin':
      return { to: '/p/$slug/settings', params }
    default:
      return { to: '/p/$slug', params }
  }
}

/** Same-origin taiga-front paths that the app can open itself. */
export function isLegacyPath(pathname: string) {
  return /^\/(project|profile|login|invitation|discover)(\/|$)/.test(pathname)
}
