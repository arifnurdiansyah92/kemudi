import { useState } from 'react'
import { format } from 'date-fns'
import { Ban } from 'lucide-react'
import { KINDS, useRefItem, useUpdateItem } from '@/lib/taiga/items'
import type { Item, ItemKind, Project } from '@/lib/taiga/types'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { can, useProject, useRefParam } from '@/features/project/use-project'
import { Attachments } from './attachments'
import { Conversation } from './conversation'
import { CustomFields } from './custom-fields'
import { Description } from './description'
import {
  AssigneeField,
  AttributeField,
  ColorField,
  DueDateField,
  FlagsField,
  IocaineField,
  PointsField,
  SprintField,
  StatusField,
  TagsField,
} from './fields'
import { ItemActions } from './item-actions'
import { StoryTasks } from './story-tasks'

/** Side sheet for whatever item `?ref=<n>` names: story, task, issue or epic. */
export function ItemSheet() {
  const project = useProject()
  const { openRef, close } = useRefParam()
  const loaded = useRefItem(project, openRef)

  return (
    <Sheet open={openRef !== undefined} onOpenChange={(o) => !o && close()}>
      <SheetContent
        side='right'
        className='flex w-full flex-col gap-0 p-0 sm:max-w-xl lg:max-w-2xl'
      >
        {loaded.isError ? (
          <div className='p-6'>
            <SheetTitle>Nothing at #{openRef}</SheetTitle>
            <SheetDescription className='mt-1'>
              {project.name} has no story, task, issue or epic #{openRef}. It
              may have been deleted.
            </SheetDescription>
          </div>
        ) : !loaded.data ? (
          <div className='space-y-3 p-6'>
            <SheetTitle className='sr-only'>Loading #{openRef}</SheetTitle>
            <SheetDescription className='sr-only'>
              Loading the item.
            </SheetDescription>
            <Skeleton className='h-4 w-16' />
            <Skeleton className='h-7 w-3/4' />
            <Skeleton className='h-24 w-full' />
          </div>
        ) : (
          <ItemBody
            key={`${loaded.data.kind}-${loaded.data.item.id}`}
            project={project}
            kind={loaded.data.kind}
            item={loaded.data.item}
            onDeleted={close}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}

function ItemBody({
  project,
  kind,
  item,
  onDeleted,
}: {
  project: Project
  kind: ItemKind
  item: Item
  onDeleted: () => void
}) {
  const { open } = useRefParam()
  const editable = can(project, KINDS[kind].perm.modify)
  const field = { project, kind, item, editable }
  const parent = item.user_story_extra_info

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <header className='border-b px-6 pt-4 pb-4'>
        <div className='flex items-center gap-2 pe-8'>
          <SheetDescription className='min-w-0 flex-1 truncate text-xs tabular-nums'>
            {KINDS[kind].label} #{item.ref}
            {parent && (
              <>
                {' in '}
                <button
                  onClick={() => open(parent.ref)}
                  className='underline-offset-4 hover:text-foreground hover:underline'
                >
                  #{parent.ref} {parent.subject}
                </button>
              </>
            )}
            {kind === 'userstory' &&
              (item.milestone_name
                ? ` in ${item.milestone_name}`
                : ' in the backlog')}
          </SheetDescription>
          <ItemActions
            project={project}
            kind={kind}
            item={item}
            onDeleted={onDeleted}
          />
        </div>
        <Subject
          key={item.subject}
          project={project}
          kind={kind}
          item={item}
          editable={editable}
        />
      </header>

      <div className='flex-1 overflow-y-auto'>
        {item.is_blocked && (
          <div
            role='status'
            className='flex gap-2 border-b border-destructive/30 bg-destructive/10 px-6 py-3 text-sm'
          >
            <Ban className='mt-0.5 size-4 shrink-0 text-destructive' />
            <p>
              <span className='font-medium text-destructive'>Blocked. </span>
              {item.blocked_note || 'No reason given.'}
            </p>
          </div>
        )}

        <dl className='grid grid-cols-[7rem_1fr] items-center gap-x-4 gap-y-3 px-6 py-5 text-sm'>
          <dt className='text-muted-foreground'>Status</dt>
          <dd>
            <StatusField {...field} />
          </dd>
          {kind === 'issue' && (
            <>
              <dt className='text-muted-foreground'>Type</dt>
              <dd>
                <AttributeField {...field} field='type' />
              </dd>
              <dt className='text-muted-foreground'>Severity</dt>
              <dd>
                <AttributeField {...field} field='severity' />
              </dd>
              <dt className='text-muted-foreground'>Priority</dt>
              <dd>
                <AttributeField {...field} field='priority' />
              </dd>
            </>
          )}
          <dt className='text-muted-foreground'>
            {kind === 'userstory' ? 'Assignees' : 'Assignee'}
          </dt>
          <dd className='min-w-0'>
            <AssigneeField {...field} />
          </dd>
          {kind === 'userstory' && (
            <>
              <dt className='self-start pt-1.5 text-muted-foreground'>
                Points
              </dt>
              <dd>
                <PointsField {...field} />
              </dd>
            </>
          )}
          {(kind === 'userstory' || kind === 'issue') && (
            <>
              <dt className='text-muted-foreground'>Sprint</dt>
              <dd>
                <SprintField {...field} />
              </dd>
            </>
          )}
          {kind === 'epic' && (
            <>
              <dt className='text-muted-foreground'>Colour</dt>
              <dd>
                <ColorField {...field} />
              </dd>
            </>
          )}
          {kind !== 'epic' && (
            <>
              <dt className='text-muted-foreground'>Due date</dt>
              <dd>
                <DueDateField {...field} />
              </dd>
            </>
          )}
          <dt className='self-start pt-1 text-muted-foreground'>Tags</dt>
          <dd>
            <TagsField {...field} />
          </dd>
          {kind === 'userstory' && (
            <>
              <dt className='text-muted-foreground'>Requirement</dt>
              <dd>
                <FlagsField {...field} />
              </dd>
            </>
          )}
          {kind === 'task' && (
            <>
              <dt className='text-muted-foreground'>Flags</dt>
              <dd>
                <IocaineField {...field} />
              </dd>
            </>
          )}
          {kind === 'userstory' && item.epics && item.epics.length > 0 && (
            <>
              <dt className='text-muted-foreground'>Epics</dt>
              <dd className='flex flex-wrap gap-1.5'>
                {item.epics.map((epic) => (
                  <button
                    key={epic.id}
                    onClick={() => open(epic.ref)}
                    className='inline-flex h-6 items-center gap-1.5 rounded-sm border px-1.5 text-xs hover:bg-accent'
                  >
                    <span
                      aria-hidden='true'
                      className='size-2 rounded-full'
                      style={{ backgroundColor: epic.color }}
                    />
                    #{epic.ref} {epic.subject}
                  </button>
                ))}
              </dd>
            </>
          )}
          <dt className='text-muted-foreground'>Created</dt>
          <dd className='text-muted-foreground'>
            {format(new Date(item.created_date), 'd MMM yyyy')}
            {item.owner_extra_info &&
              ` by ${item.owner_extra_info.full_name_display}`}
          </dd>
        </dl>

        <Section title='Description'>
          <Description {...field} />
        </Section>

        {kind === 'userstory' && (
          <Section title='Tasks'>
            <StoryTasks project={project} story={item} />
          </Section>
        )}

        <CustomFields {...field} />

        <Section title='Attachments'>
          <Attachments project={project} kind={kind} item={item} />
        </Section>

        <section className='border-t px-6 py-5'>
          <Conversation project={project} kind={kind} item={item} />
        </section>
      </div>
    </div>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className='border-t px-6 py-5'>
      <h3 className='mb-3 text-sm font-semibold'>{title}</h3>
      {children}
    </section>
  )
}

function Subject({
  project,
  kind,
  item,
  editable,
}: {
  project: Project
  kind: ItemKind
  item: Item
  editable: boolean
}) {
  const update = useUpdateItem(project, kind)
  const [value, setValue] = useState(item.subject)

  const save = () => {
    const next = value.trim()
    if (!next) return setValue(item.subject)
    if (next !== item.subject) update.mutate({ item, patch: { subject: next } })
  }

  if (!editable)
    return (
      <SheetTitle className='mt-1 text-xl leading-snug font-semibold'>
        {item.subject}
      </SheetTitle>
    )

  return (
    <>
      <SheetTitle className='sr-only'>{item.subject}</SheetTitle>
      <textarea
        aria-label='Subject'
        value={value}
        rows={1}
        maxLength={500}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            e.currentTarget.blur()
          }
          if (e.key === 'Escape') setValue(item.subject)
        }}
        className='-mx-1 mt-1 field-sizing-content w-full resize-none rounded-md bg-transparent px-1 text-xl leading-snug font-semibold outline-none hover:bg-accent/50 focus:bg-accent/50 focus-visible:ring-2 focus-visible:ring-ring'
      />
    </>
  )
}
