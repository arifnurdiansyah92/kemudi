import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Id, Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

type Field = 'color' | 'closed' | 'archived' | 'wip' | 'value' | 'days'

type ListConfig = {
  title: string
  description: string
  endpoint: string
  /** Body key of the bulk order endpoint; absent means order is PATCHed. */
  bulkParam?: string
  fields: Field[]
  /** Deleting needs somewhere to move the items that use the value. */
  moveOnDelete: boolean
}

interface Row {
  id: Id
  name: string
  order: number
  color?: string
  is_closed?: boolean
  is_archived?: boolean
  wip_limit?: number | null
  value?: number | null
  days_to_due?: number | null
}

const LISTS: Record<string, ListConfig[]> = {
  Stories: [
    {
      title: 'Statuses',
      description:
        'The columns of the kanban and the steps a story goes through.',
      endpoint: 'userstory-statuses',
      bulkParam: 'bulk_userstory_statuses',
      fields: ['color', 'closed', 'archived', 'wip'],
      moveOnDelete: true,
    },
    {
      title: 'Points',
      description: 'The values people can estimate a story with.',
      endpoint: 'points',
      bulkParam: 'bulk_points',
      fields: ['value'],
      moveOnDelete: true,
    },
    {
      title: 'Swimlanes',
      description: 'Rows on the kanban board.',
      endpoint: 'swimlanes',
      bulkParam: 'bulk_swimlanes',
      fields: [],
      moveOnDelete: true,
    },
    {
      title: 'Due date warnings',
      description: 'Highlight stories this many days before they are due.',
      endpoint: 'userstory-due-dates',
      fields: ['color', 'days'],
      moveOnDelete: false,
    },
  ],
  Tasks: [
    {
      title: 'Statuses',
      description: 'The columns of the taskboard.',
      endpoint: 'task-statuses',
      bulkParam: 'bulk_task_statuses',
      fields: ['color', 'closed'],
      moveOnDelete: true,
    },
    {
      title: 'Due date warnings',
      description: 'Highlight tasks this many days before they are due.',
      endpoint: 'task-due-dates',
      fields: ['color', 'days'],
      moveOnDelete: false,
    },
  ],
  Issues: [
    {
      title: 'Statuses',
      description: 'The steps an issue goes through.',
      endpoint: 'issue-statuses',
      bulkParam: 'bulk_issue_statuses',
      fields: ['color', 'closed'],
      moveOnDelete: true,
    },
    {
      title: 'Types',
      description: 'Kinds of issue, such as bug or question.',
      endpoint: 'issue-types',
      bulkParam: 'bulk_issue_types',
      fields: ['color'],
      moveOnDelete: true,
    },
    {
      title: 'Priorities',
      description: 'How soon an issue should be dealt with.',
      endpoint: 'priorities',
      bulkParam: 'bulk_priorities',
      fields: ['color'],
      moveOnDelete: true,
    },
    {
      title: 'Severities',
      description: 'How bad the effect of an issue is.',
      endpoint: 'severities',
      bulkParam: 'bulk_severities',
      fields: ['color'],
      moveOnDelete: true,
    },
    {
      title: 'Due date warnings',
      description: 'Highlight issues this many days before they are due.',
      endpoint: 'issue-due-dates',
      fields: ['color', 'days'],
      moveOnDelete: false,
    },
  ],
  Epics: [
    {
      title: 'Statuses',
      description: 'The steps an epic goes through.',
      endpoint: 'epic-statuses',
      bulkParam: 'bulk_epic_statuses',
      fields: ['color', 'closed'],
      moveOnDelete: true,
    },
  ],
}

export function AttributesSettings() {
  const project = useProject()
  return (
    <Tabs defaultValue='Stories'>
      <TabsList>
        {Object.keys(LISTS).map((k) => (
          <TabsTrigger key={k} value={k}>
            {k}
          </TabsTrigger>
        ))}
      </TabsList>
      {Object.entries(LISTS).map(([k, lists]) => (
        <TabsContent key={k} value={k} className='mt-4 grid gap-6'>
          {lists.map((cfg) => (
            <AttributeList key={cfg.endpoint} project={project} cfg={cfg} />
          ))}
        </TabsContent>
      ))}
    </Tabs>
  )
}

function useAttributeList(project: Project, cfg: ListConfig) {
  const qc = useQueryClient()
  const key = ['attributes', cfg.endpoint, project.id]
  const settle = () => {
    qc.invalidateQueries({ queryKey: key })
    qc.invalidateQueries({ queryKey: ['project'] })
    if (cfg.endpoint === 'swimlanes')
      qc.invalidateQueries({ queryKey: ['swimlanes'] })
  }
  const list = useQuery({
    queryKey: key,
    queryFn: async () =>
      (
        await api.get<Row[]>(`/${cfg.endpoint}`, {
          params: { project: project.id },
        })
      ).data.sort((a, b) => a.order - b.order),
  })
  const update = useMutation({
    mutationFn: ({ row, patch }: { row: Row; patch: Partial<Row> }) =>
      api.patch(`/${cfg.endpoint}/${row.id}`, patch),
    onError: onFail,
    onSettled: settle,
  })
  const create = useMutation({
    mutationFn: (input: Partial<Row>) =>
      api.post(`/${cfg.endpoint}`, {
        project: project.id,
        order: (list.data?.length ?? 0) + 1,
        ...input,
      }),
    onError: onFail,
    onSettled: settle,
  })
  const remove = useMutation({
    mutationFn: ({ row, moveTo }: { row: Row; moveTo?: Id }) =>
      api.delete(`/${cfg.endpoint}/${row.id}`, {
        params: moveTo ? { moveTo } : undefined,
      }),
    onError: onFail,
    onSettled: settle,
  })
  const reorder = useMutation({
    mutationFn: async (rows: Row[]) => {
      if (cfg.bulkParam)
        return api.post(`/${cfg.endpoint}/bulk_update_order`, {
          project: project.id,
          [cfg.bulkParam]: rows.map((r, i) => [r.id, i + 1]),
        })
      await Promise.all(
        rows.map((r, i) =>
          r.order === i + 1
            ? null
            : api.patch(`/${cfg.endpoint}/${r.id}`, { order: i + 1 })
        )
      )
    },
    onMutate: (rows) =>
      qc.setQueryData(
        key,
        rows.map((r, i) => ({ ...r, order: i + 1 }))
      ),
    onError: onFail,
    onSettled: settle,
  })
  return { list, update, create, remove, reorder }
}

function AttributeList({
  project,
  cfg,
}: {
  project: Project
  cfg: ListConfig
}) {
  const a = useAttributeList(project, cfg)
  const [name, setName] = useState('')
  const [deleting, setDeleting] = useState<Row | null>(null)
  const [moveTo, setMoveTo] = useState<Id | ''>('')
  const rows = a.list.data ?? []
  const has = (f: Field) => cfg.fields.includes(f)

  const move = (i: number, dir: -1 | 1) => {
    const next = [...rows]
    ;[next[i], next[i + dir]] = [next[i + dir], next[i]]
    a.reorder.mutate(next)
  }

  return (
    <SettingsSection title={cfg.title} description={cfg.description}>
      {a.list.isPending ? (
        <Skeleton className='h-24 w-full' />
      ) : (
        <ul className='grid gap-1.5'>
          {rows.map((row, i) => (
            <li
              key={`${row.id}-${row.order}`}
              className='flex flex-wrap items-center gap-2'
            >
              <span className='flex flex-col'>
                <button
                  aria-label={`Move ${row.name} up`}
                  disabled={i === 0}
                  onClick={() => move(i, -1)}
                  className='rounded text-muted-foreground hover:text-foreground disabled:opacity-30'
                >
                  <ArrowUp className='size-3.5' />
                </button>
                <button
                  aria-label={`Move ${row.name} down`}
                  disabled={i === rows.length - 1}
                  onClick={() => move(i, 1)}
                  className='rounded text-muted-foreground hover:text-foreground disabled:opacity-30'
                >
                  <ArrowDown className='size-3.5' />
                </button>
              </span>
              {has('color') && (
                <input
                  type='color'
                  aria-label={`Colour of ${row.name}`}
                  defaultValue={row.color ?? '#999999'}
                  onBlur={(e) =>
                    e.target.value !== row.color &&
                    a.update.mutate({ row, patch: { color: e.target.value } })
                  }
                  className='h-8 w-9 cursor-pointer rounded border bg-transparent'
                />
              )}
              <Input
                aria-label='Name'
                defaultValue={row.name}
                onBlur={(e) => {
                  const v = e.target.value.trim()
                  if (v && v !== row.name)
                    a.update.mutate({ row, patch: { name: v } })
                }}
                onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
                className='h-8 w-48'
              />
              {has('value') && (
                <Input
                  type='number'
                  step='any'
                  aria-label={`Value of ${row.name}`}
                  placeholder='No value'
                  defaultValue={row.value ?? ''}
                  onBlur={(e) => {
                    const v =
                      e.target.value === '' ? null : Number(e.target.value)
                    if (v !== row.value)
                      a.update.mutate({ row, patch: { value: v } })
                  }}
                  className='h-8 w-24'
                />
              )}
              {has('days') && (
                <label className='flex items-center gap-1.5 text-xs text-muted-foreground'>
                  <Input
                    type='number'
                    aria-label={`Days before due for ${row.name}`}
                    placeholder='–'
                    defaultValue={row.days_to_due ?? ''}
                    onBlur={(e) => {
                      const v =
                        e.target.value === '' ? null : Number(e.target.value)
                      if (v !== row.days_to_due)
                        a.update.mutate({ row, patch: { days_to_due: v } })
                    }}
                    className='h-8 w-20'
                  />
                  days before
                </label>
              )}
              {has('wip') && (
                <label className='flex items-center gap-1.5 text-xs text-muted-foreground'>
                  WIP
                  <Input
                    type='number'
                    min={0}
                    aria-label={`Work in progress limit of ${row.name}`}
                    placeholder='none'
                    defaultValue={row.wip_limit ?? ''}
                    onBlur={(e) => {
                      const v =
                        e.target.value === '' ? null : Number(e.target.value)
                      if (v !== row.wip_limit)
                        a.update.mutate({ row, patch: { wip_limit: v } })
                    }}
                    className='h-8 w-20'
                  />
                </label>
              )}
              {has('closed') && (
                <Flag
                  on={!!row.is_closed}
                  label='Closed'
                  title='Items in this status count as done'
                  onClick={() =>
                    a.update.mutate({
                      row,
                      patch: { is_closed: !row.is_closed },
                    })
                  }
                />
              )}
              {has('archived') && (
                <Flag
                  on={!!row.is_archived}
                  label='Archived'
                  title='Hidden from the kanban unless archived is shown'
                  onClick={() =>
                    a.update.mutate({
                      row,
                      patch: { is_archived: !row.is_archived },
                    })
                  }
                />
              )}
              <Button
                variant='ghost'
                size='icon'
                className='ms-auto size-8 text-muted-foreground'
                aria-label={`Delete ${row.name}`}
                disabled={
                  cfg.moveOnDelete &&
                  cfg.endpoint !== 'swimlanes' &&
                  rows.length < 2
                }
                onClick={() => {
                  setDeleting(row)
                  setMoveTo(rows.find((r) => r.id !== row.id)?.id ?? '')
                }}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        className='mt-3 flex gap-2'
        onSubmit={(e) => {
          e.preventDefault()
          if (!name.trim()) return
          a.create.mutate(
            {
              name: name.trim(),
              ...(has('color') ? { color: '#A9AABC' } : {}),
            },
            { onSuccess: () => setName('') }
          )
        }}
      >
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={`New ${cfg.title.toLowerCase().replace(/s$/, '')}`}
          aria-label={`New ${cfg.title.toLowerCase()}`}
          className='h-8 w-60'
        />
        <Button size='sm' variant='outline' disabled={!name.trim()}>
          <Plus />
          Add
        </Button>
      </form>

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.name ?? ''}?`}
        desc={
          cfg.moveOnDelete && rows.length > 1 ? (
            <span className='grid gap-2'>
              <span>Everything using it moves to:</span>
              <select
                aria-label='Move to'
                value={moveTo}
                onChange={(e) => setMoveTo(Number(e.target.value))}
                className='h-9 rounded-md border bg-transparent px-2 text-sm text-foreground'
              >
                {rows
                  .filter((r) => r.id !== deleting?.id)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
              </select>
            </span>
          ) : (
            'It is removed from this project.'
          )
        }
        confirmText='Delete'
        destructive
        isLoading={a.remove.isPending}
        handleConfirm={() =>
          deleting &&
          a.remove.mutate(
            {
              row: deleting,
              moveTo: cfg.moveOnDelete && moveTo ? moveTo : undefined,
            },
            { onSuccess: () => setDeleting(null) }
          )
        }
      />
    </SettingsSection>
  )
}

function Flag({
  on,
  label,
  title,
  onClick,
}: {
  on: boolean
  label: string
  title: string
  onClick: () => void
}) {
  return (
    <button
      aria-pressed={on}
      title={title}
      onClick={onClick}
      className={cn(
        'h-8 rounded-full border px-3 text-xs',
        on
          ? 'border-primary bg-primary text-primary-foreground'
          : 'text-muted-foreground hover:bg-accent'
      )}
    >
      {label}
    </button>
  )
}
