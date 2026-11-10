/**
 * Live updates from kemudi-events (taiga-events). The server pushes
 * `{routing_key, session_id, data: {type, matches, pk}}`; we refetch the
 * affected queries. Every API request carries this tab's session id, so the
 * server does not echo our own changes back.
 */
import { useEffect } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { useAuthStore } from '@/stores/auth-store'
import { api } from './client'

export const sessionId =
  globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`

api.interceptors.request.use((config) => {
  config.headers['X-Session-Id'] = sessionId
  return config
})

/** Query key prefixes to refetch for each changed model. */
const AFFECTS: Record<string, string[]> = {
  'userstories.userstory': [
    'stories',
    'item',
    'epic-stories',
    'my-items',
    'project-stats',
    'sprint-stats',
    'search',
  ],
  'tasks.task': [
    'tasks',
    'sprint-tasks',
    'item',
    'my-items',
    'sprint-stats',
    'search',
  ],
  'issues.issue': ['issues', 'item', 'my-items', 'search'],
  'epics.epic': ['epics', 'item', 'search'],
  'epics.relateduserstory': ['epics', 'epic-stories', 'item', 'stories'],
  'milestones.milestone': ['milestones', 'sprint', 'sprint-stats', 'stories'],
  'wiki.wikipage': ['wiki'],
  'wiki.wikilink': ['wiki-links'],
  'projects.project': ['project', 'projects'],
  'projects.membership': ['project'],
  'projects.swimlane': ['swimlanes'],
}

function invalidator(qc: QueryClient) {
  const pending = new Set<string>()
  let timer: number | undefined
  return (prefixes: string[]) => {
    prefixes.forEach((p) => pending.add(p))
    window.clearTimeout(timer)
    // Bulk changes arrive as bursts; refetch once they settle.
    timer = window.setTimeout(() => {
      for (const p of pending) qc.invalidateQueries({ queryKey: [p] })
      pending.clear()
    }, 300)
  }
}

function eventsUrl() {
  const base = import.meta.env.VITE_EVENTS_URL as string | undefined
  if (base) return base
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${window.location.host}/events`
}

/** Keeps one socket open while signed in; follows the open project. */
export function useLiveUpdates() {
  const qc = useQueryClient()
  const token = useAuthStore((s) => s.session?.token)
  const userId = useAuthStore((s) => s.session?.user.id)
  const { slug } = useParams({ strict: false }) as { slug?: string }
  const projectId = slug
    ? qc.getQueryData<{ id: number }>(['project', slug])?.id
    : undefined

  useEffect(() => {
    if (!token || !userId) return
    let socket: WebSocket | null = null
    let ping: number | undefined
    let retry: number | undefined
    let attempts = 0
    let closed = false
    const invalidate = invalidator(qc)

    const send = (msg: object) => socket?.send(JSON.stringify(msg))

    const connect = () => {
      socket = new WebSocket(eventsUrl())
      socket.onopen = () => {
        attempts = 0
        send({ cmd: 'auth', data: { token, sessionId } })
        send({ cmd: 'subscribe', routing_key: `web_notifications.${userId}` })
        if (projectId)
          send({
            cmd: 'subscribe',
            routing_key: `changes.project.${projectId}.#`,
          })
        ping = window.setInterval(() => send({ cmd: 'ping' }), 30_000)
      }
      socket.onmessage = (e) => {
        let msg: { routing_key?: string; data?: { matches?: string } }
        try {
          msg = JSON.parse(e.data)
        } catch {
          return
        }
        if (msg.routing_key?.startsWith('web_notifications.'))
          return invalidate(['notifications'])
        const matches = msg.data?.matches
        if (matches && AFFECTS[matches]) invalidate(AFFECTS[matches])
      }
      socket.onclose = () => {
        window.clearInterval(ping)
        if (closed) return
        // Back off up to 30 s while the events service is away.
        attempts += 1
        retry = window.setTimeout(
          connect,
          Math.min(30_000, 1000 * 2 ** attempts)
        )
      }
    }
    connect()

    return () => {
      closed = true
      window.clearInterval(ping)
      window.clearTimeout(retry)
      socket?.close()
    }
  }, [qc, token, userId, projectId])
}
