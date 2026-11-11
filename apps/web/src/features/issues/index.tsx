import { useMemo, useState } from 'react'
import i18n from '@/i18n'
import { useFormat } from '@/i18n/format'
import { ArrowDown, ArrowUp, Plus, ThumbsUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useIssues } from '@/lib/taiga/issues'
import type { Attribute, Item, Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { UserAvatar } from '@/components/user-avatar'
import {
  applyFilters,
  emptyFilters,
  type Facet,
} from '@/features/filters/apply'
import { assigneeFacet, statusFacet, tagFacet } from '@/features/filters/facets'
import { FilterBar } from '@/features/filters/filter-bar'
import { can, useProject, useRefParam } from '@/features/project/use-project'
import { StatusDot } from '@/features/story/parts'
import { CreateIssueDialog } from './create-issue-dialog'

type SortKey =
  | 'type'
  | 'severity'
  | 'priority'
  | 'ref'
  | 'status'
  | 'assignee'
  | 'modified'
  | 'votes'

/** Facet labels, read at render so they follow the UI language. */
const attributeLabels = {
  type: () => i18n.t('common:terms.type'),
  severity: () => i18n.t('common:terms.severity'),
  priority: () => i18n.t('common:terms.priority'),
}

function attributeFacet(
  key: 'type' | 'severity' | 'priority',
  options: Attribute[]
): Facet<Item> {
  return {
    key,
    get label() {
      return attributeLabels[key]()
    },
    options: [...options]
      .sort((a, b) => a.order - b.order)
      .map((o) => ({ value: o.id, label: o.name, color: o.color })),
    values: (item) => (item[key] ? [item[key]!] : []),
  }
}

function orderOf(list: { id: number; order: number }[], id?: number | null) {
  return list.find((x) => x.id === id)?.order ?? 0
}

export function Issues() {
  const { t } = useTranslation(['board', 'common'])
  const project = useProject()
  const issues = useIssues(project.id)
  const { open } = useRefParam()
  const [filters, setFilters] = useState(emptyFilters)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: 'modified',
    desc: true,
  })
  const [creating, setCreating] = useState(false)
  const list = useMemo(() => issues.data ?? [], [issues.data])

  const facets = useMemo(
    () => [
      attributeFacet('type', project.issue_types),
      attributeFacet('severity', project.severities),
      attributeFacet('priority', project.priorities),
      statusFacet<Item>(project.issue_statuses),
      assigneeFacet<Item>(project),
      tagFacet(project, list),
    ],
    [project, list]
  )

  const rows = useMemo(() => {
    const shown = applyFilters(list, facets, filters)
    const value = (i: Item): number | string => {
      switch (sort.key) {
        case 'type':
          return orderOf(project.issue_types, i.type)
        case 'severity':
          return orderOf(project.severities, i.severity)
        case 'priority':
          return orderOf(project.priorities, i.priority)
        case 'status':
          return orderOf(project.issue_statuses, i.status)
        case 'assignee':
          return i.assigned_to_extra_info?.full_name_display ?? '~'
        case 'votes':
          return i.total_voters ?? 0
        case 'ref':
          return i.ref
        default:
          return i.modified_date
      }
    }
    return [...shown].sort((a, b) => {
      const va = value(a)
      const vb = value(b)
      const cmp = va < vb ? -1 : va > vb ? 1 : 0
      return sort.desc ? -cmp : cmp
    })
  }, [list, facets, filters, sort, project])

  const canAdd = can(project, 'add_issue')
  const columns: [SortKey, string, string?][] = [
    ['type', t('common:terms.type'), 'max-md:hidden'],
    ['severity', t('common:terms.severity'), 'max-lg:hidden'],
    ['priority', t('common:terms.priority'), 'max-lg:hidden'],
    ['ref', t('common:terms.issue', { count: 1 })],
    ['status', t('common:terms.status')],
    ['assignee', t('common:terms.assignee'), 'max-md:hidden'],
    ['votes', t('issues.columns.votes'), 'max-lg:hidden'],
    ['modified', t('issues.columns.updated'), 'max-sm:hidden'],
  ]

  const header = (key: SortKey, label: string, className?: string) => (
    <th
      key={key}
      scope='col'
      aria-sort={
        sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'
      }
      className={cn('px-3 py-2 text-start font-medium', className)}
    >
      <button
        className='inline-flex items-center gap-1 hover:text-foreground'
        onClick={() =>
          setSort((s) => ({
            key,
            desc: s.key === key ? !s.desc : key === 'modified',
          }))
        }
      >
        {label}
        {sort.key === key &&
          (sort.desc ? (
            <ArrowDown className='size-3' />
          ) : (
            <ArrowUp className='size-3' />
          ))}
      </button>
    </th>
  )

  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          { label: t('common:terms.issue', { count: 2 }) },
        ]}
      />
      <Main width='table'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold tracking-tight'>
              {t('common:terms.issue', { count: 2 })}
            </h1>
            {issues.data && (
              <p className='mt-1 text-sm text-muted-foreground tabular-nums'>
                {t('issues.summary', {
                  open: list.filter((i) => !i.is_closed).length,
                  closed: list.filter((i) => i.is_closed).length,
                })}
              </p>
            )}
          </div>
          {canAdd && (
            <Button size='sm' onClick={() => setCreating(true)}>
              <Plus />
              {t('issues.new')}
            </Button>
          )}
        </div>

        <FilterBar
          savedKey={`${project.id}:kemudi-filters-issues`}
          items={list}
          facets={facets}
          value={filters}
          onChange={setFilters}
          className='mt-6'
        />

        <div className='mt-4 overflow-x-auto rounded-lg border bg-card'>
          {issues.isPending ? (
            <div className='space-y-px p-2'>
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className='h-10 w-full' />
              ))}
            </div>
          ) : list.length === 0 ? (
            <p className='px-4 py-12 text-center text-sm text-muted-foreground'>
              {t('issues.empty')} {canAdd && t('issues.emptyHint')}
            </p>
          ) : rows.length === 0 ? (
            <p className='px-4 py-12 text-center text-sm text-muted-foreground'>
              {t('issues.noMatch')}
            </p>
          ) : (
            <table className='w-full text-sm'>
              <thead className='border-b text-xs text-muted-foreground'>
                <tr>
                  {columns.map(([key, label, className]) =>
                    header(key, label, className)
                  )}
                </tr>
              </thead>
              <tbody className='divide-y'>
                {rows.map((issue) => (
                  <IssueRow
                    key={issue.id}
                    project={project}
                    issue={issue}
                    onOpen={() => open(issue.ref)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Main>
      {creating && (
        <CreateIssueDialog
          project={project}
          open={creating}
          onOpenChange={setCreating}
          onCreated={(ref) => open(ref)}
        />
      )}
    </>
  )
}

function Attr({ list, id }: { list: Attribute[]; id?: number | null }) {
  const a = list.find((x) => x.id === id)
  if (!a) return <span className='text-muted-foreground'>–</span>
  return (
    <span className='inline-flex items-center gap-1.5 whitespace-nowrap'>
      <StatusDot color={a.color} />
      {a.name}
    </span>
  )
}

function IssueRow({
  project,
  issue,
  onOpen,
}: {
  project: Project
  issue: Item
  onOpen: () => void
}) {
  const { t } = useTranslation(['board', 'common'])
  const format = useFormat()
  const assignee = project.members.find((m) => m.id === issue.assigned_to)
  return (
    <tr
      className={cn(
        'hover:bg-accent/40',
        issue.is_closed && 'text-muted-foreground'
      )}
    >
      <td className='px-3 py-2 max-md:hidden'>
        <Attr list={project.issue_types} id={issue.type} />
      </td>
      <td className='px-3 py-2 max-lg:hidden'>
        <Attr list={project.severities} id={issue.severity} />
      </td>
      <td className='px-3 py-2 max-lg:hidden'>
        <Attr list={project.priorities} id={issue.priority} />
      </td>
      <td className='max-w-0 px-3 py-2 sm:w-1/2'>
        <button
          onClick={onOpen}
          className={cn(
            'block w-full truncate text-start hover:underline hover:underline-offset-4',
            issue.is_closed && 'line-through'
          )}
        >
          <span className='me-2 text-xs text-muted-foreground tabular-nums'>
            #{issue.ref}
          </span>
          {issue.subject}
        </button>
      </td>
      <td className='px-3 py-2'>
        <span className='inline-flex items-center gap-1.5 whitespace-nowrap'>
          <StatusDot color={issue.status_extra_info.color} />
          {issue.status_extra_info.name}
        </span>
      </td>
      <td className='px-3 py-2 max-md:hidden'>
        {assignee ? (
          <span className='inline-flex items-center gap-2 whitespace-nowrap'>
            <UserAvatar user={assignee} className='size-5' />
            {assignee.full_name_display}
          </span>
        ) : (
          <span className='text-muted-foreground'>
            {t('common:status.unassigned')}
          </span>
        )}
      </td>
      <td className='px-3 py-2 tabular-nums max-lg:hidden'>
        <span className='inline-flex items-center gap-1'>
          <ThumbsUp className='size-3 text-muted-foreground' />
          {issue.total_voters ?? 0}
        </span>
      </td>
      <td className='px-3 py-2 whitespace-nowrap text-muted-foreground max-sm:hidden'>
        {format.timeAgo(issue.modified_date)}
      </td>
    </tr>
  )
}
