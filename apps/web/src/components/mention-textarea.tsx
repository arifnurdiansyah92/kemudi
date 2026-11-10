import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/taiga/client'
import type { Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Textarea } from '@/components/ui/textarea'
import { UserAvatar } from '@/components/user-avatar'

type Suggestion = {
  key: string
  insert: string
  label: string
  hint?: string
  avatar?: Project['members'][number]
}
type SearchHit = { id: number; ref?: number; subject?: string }

/** The @word or #word being typed just before the caret, if any. */
function activeToken(text: string, caret: number) {
  const m = /(^|\s)([@#])([\w.-]*)$/.exec(text.slice(0, caret))
  return m
    ? {
        trigger: m[2] as '@' | '#',
        query: m[3],
        start: caret - m[3].length - 1,
      }
    : null
}

/**
 * A textarea that suggests project members after "@" and stories, tasks,
 * issues and epics after "#", as Taiga's editor does. Up and Down move,
 * Enter or Tab inserts, Escape closes.
 */
export function MentionTextarea({
  project,
  value,
  onChange,
  onKeyDown,
  className,
  ...props
}: Omit<React.ComponentProps<typeof Textarea>, 'value' | 'onChange'> & {
  project: Project
  value: string
  onChange: (value: string) => void
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  const [caret, setCaret] = useState(0)
  const [activeState, setActive] = useState({ key: '', index: 0 })
  const pendingCaret = useRef<number | null>(null)
  const [dismissed, setDismissed] = useState<number | null>(null)
  const token = activeToken(value, caret)
  const open = !!token && dismissed !== token.start
  const tokenKey = token ? `${token.trigger}${token.start}:${token.query}` : ''
  // The highlight starts over whenever the typed word changes.
  const active = activeState.key === tokenKey ? activeState.index : 0

  const refs = useQuery({
    queryKey: ['mention-search', project.id, token?.query],
    enabled: open && token?.trigger === '#' && token.query.length > 0,
    staleTime: 30_000,
    queryFn: async () => {
      const { data } = await api.get<Record<string, SearchHit[]>>('/search', {
        params: { project: project.id, text: token!.query },
      })
      return ['userstories', 'tasks', 'issues', 'epics'].flatMap((k) =>
        (data[k] ?? []).map((h) => ({ ...h, kind: k }))
      )
    },
  })

  const suggestions: Suggestion[] = useMemo(() => {
    if (!open || !token) return []
    const q = token.query.toLowerCase()
    if (token.trigger === '@')
      return project.members
        .filter((m) => m.is_active)
        .filter(
          (m) =>
            !q ||
            m.username.toLowerCase().includes(q) ||
            m.full_name_display.toLowerCase().includes(q)
        )
        .slice(0, 8)
        .map((m) => ({
          key: `u${m.id}`,
          insert: `@${m.username} `,
          label: m.full_name_display,
          hint: `@${m.username}`,
          avatar: m,
        }))
    return (refs.data ?? [])
      .filter((h) => h.ref)
      .slice(0, 8)
      .map((h) => ({
        key: `${h.kind}${h.id}`,
        insert: `#${h.ref} `,
        label: h.subject ?? '',
        hint: `#${h.ref}`,
      }))
  }, [open, token, project.members, refs.data])

  const pick = (s: Suggestion) => {
    if (!token) return
    const next = value.slice(0, token.start) + s.insert + value.slice(caret)
    const pos = token.start + s.insert.length
    // Place the caret right after the insert before any next keystroke.
    pendingCaret.current = pos
    setCaret(pos)
    onChange(next)
  }

  useLayoutEffect(() => {
    const pos = pendingCaret.current
    if (pos === null || !ref.current) return
    pendingCaret.current = null
    ref.current.focus()
    ref.current.setSelectionRange(pos, pos)
  }, [value])

  return (
    <div className='relative'>
      <Textarea
        {...props}
        ref={ref}
        value={value}
        className={className}
        role='combobox'
        aria-expanded={open && suggestions.length > 0}
        aria-autocomplete='list'
        onChange={(e) => {
          onChange(e.target.value)
          setCaret(e.target.selectionStart)
        }}
        onSelect={(e) => setCaret(e.currentTarget.selectionStart)}
        onKeyDown={(e) => {
          if (open && suggestions.length > 0) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault()
              const d = e.key === 'ArrowDown' ? 1 : -1
              setActive({
                key: tokenKey,
                index: (active + d + suggestions.length) % suggestions.length,
              })
              return
            }
            if (e.key === 'Enter' || e.key === 'Tab') {
              if (!(e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                pick(suggestions[active])
                return
              }
            }
            if (e.key === 'Escape') {
              e.preventDefault()
              e.stopPropagation()
              setDismissed(token!.start)
              return
            }
          }
          onKeyDown?.(e)
        }}
      />
      {open && suggestions.length > 0 && (
        <ul
          role='listbox'
          aria-label={token!.trigger === '@' ? 'People' : 'Items'}
          className='absolute inset-x-0 top-full z-50 mt-1 max-h-64 overflow-y-auto rounded-md border bg-popover p-1 text-sm shadow-md'
        >
          {suggestions.map((s, i) => (
            <li
              key={s.key}
              role='option'
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault()
                pick(s)
              }}
              onMouseEnter={() => setActive({ key: tokenKey, index: i })}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded px-2 py-1.5',
                i === active && 'bg-accent'
              )}
            >
              {s.avatar ? (
                <UserAvatar user={s.avatar} className='size-5' />
              ) : (
                <span className='w-10 text-xs text-muted-foreground tabular-nums'>
                  {s.hint}
                </span>
              )}
              <span className='truncate'>{s.label}</span>
              {s.avatar && (
                <span className='ms-auto text-xs text-muted-foreground'>
                  {s.hint}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
