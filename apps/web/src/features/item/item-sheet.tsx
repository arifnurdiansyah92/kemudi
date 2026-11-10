import { useState } from 'react'
import { useFormat } from '@/i18n/format'
import { Ban } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
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
import { EpicStories, StoryEpics } from './epic-stories'
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
  WatchersField,
} from './fields'
import { ItemActions } from './item-actions'
import { StoryTasks } from './story-tasks'

/** Each item kind's name in common:terms. */
const TERM = {
  userstory: 'story',
  task: 'task',
  issue: 'issue',
  epic: 'epic',
} as const

/** Side sheet for whatever item `?ref=<n>` names: story, task, issue or epic. */
export function ItemSheet() {
  const { t } = useTranslation(['item', 'common'])
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
            <SheetTitle>
              {t('sheet.notFoundTitle', { ref: openRef })}
            </SheetTitle>
            <SheetDescription className='mt-1'>
              {t('sheet.notFoundDesc', { project: project.name, ref: openRef })}
            </SheetDescription>
          </div>
        ) : !loaded.data ? (
          <div className='space-y-3 p-6'>
            <SheetTitle className='sr-only'>
              {t('sheet.loadingTitle', { ref: openRef })}
            </SheetTitle>
            <SheetDescription className='sr-only'>
              {t('sheet.loadingDesc')}
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
  const { t } = useTranslation(['item', 'common'])
  const fmt = useFormat()
  const { open } = useRefParam()
  const editable = can(project, KINDS[kind].perm.modify)
  const field = { project, kind, item, editable }
  const parent = item.user_story_extra_info
  const where = {
    kind: t(`common:terms.${TERM[kind]}`, { count: 1 }),
    ref: item.ref,
  }

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <header className='border-b px-6 pt-4 pb-4'>
        <div className='flex items-center gap-2 pe-8'>
          <SheetDescription className='min-w-0 flex-1 truncate text-xs tabular-nums'>
            {kind === 'userstory' ? (
              item.milestone_name ? (
                t('sheet.inSprint', { ...where, sprint: item.milestone_name })
              ) : (
                t('sheet.inBacklog', where)
              )
            ) : parent ? (
              <Trans
                t={t}
                i18nKey='sheet.inStory'
                values={{
                  ...where,
                  parentRef: parent.ref,
                  parentSubject: parent.subject,
                }}
                components={{
                  parent: (
                    <button
                      onClick={() => open(parent.ref)}
                      className='underline-offset-4 hover:text-foreground hover:underline'
                    />
                  ),
                }}
              />
            ) : (
              t('sheet.ref', where)
            )}
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
              <span className='font-medium text-destructive'>
                {t('sheet.blocked')}{' '}
              </span>
              {item.blocked_note || t('sheet.noBlockReason')}
            </p>
          </div>
        )}

        <dl className='grid grid-cols-[minmax(7rem,max-content)_1fr] items-center gap-x-4 gap-y-3 px-6 py-5 text-sm'>
          <dt className='text-muted-foreground'>{t('common:terms.status')}</dt>
          <dd>
            <StatusField {...field} />
          </dd>
          {kind === 'issue' && (
            <>
              <dt className='text-muted-foreground'>
                {t('common:terms.type')}
              </dt>
              <dd>
                <AttributeField {...field} field='type' />
              </dd>
              <dt className='text-muted-foreground'>
                {t('common:terms.severity')}
              </dt>
              <dd>
                <AttributeField {...field} field='severity' />
              </dd>
              <dt className='text-muted-foreground'>
                {t('common:terms.priority')}
              </dt>
              <dd>
                <AttributeField {...field} field='priority' />
              </dd>
            </>
          )}
          <dt className='text-muted-foreground'>
            {kind === 'userstory'
              ? t('common:terms.assignees')
              : t('common:terms.assignee')}
          </dt>
          <dd className='min-w-0'>
            <AssigneeField {...field} />
          </dd>
          {kind === 'userstory' && (
            <>
              <dt className='self-start pt-1.5 text-muted-foreground'>
                {t('common:terms.points')}
              </dt>
              <dd>
                <PointsField {...field} />
              </dd>
            </>
          )}
          {(kind === 'userstory' || kind === 'issue') && (
            <>
              <dt className='text-muted-foreground'>
                {t('common:terms.sprint', { count: 1 })}
              </dt>
              <dd>
                <SprintField {...field} />
              </dd>
            </>
          )}
          {kind === 'epic' && (
            <>
              <dt className='text-muted-foreground'>{t('sheet.colour')}</dt>
              <dd>
                <ColorField {...field} />
              </dd>
            </>
          )}
          {kind !== 'epic' && (
            <>
              <dt className='text-muted-foreground'>
                {t('common:terms.dueDate')}
              </dt>
              <dd>
                <DueDateField {...field} />
              </dd>
            </>
          )}
          <dt className='self-start pt-1 text-muted-foreground'>
            {t('common:terms.tags')}
          </dt>
          <dd>
            <TagsField {...field} />
          </dd>
          {(kind === 'userstory' || kind === 'epic') && (
            <>
              <dt className='text-muted-foreground'>
                {t('sheet.requirement')}
              </dt>
              <dd>
                <FlagsField {...field} />
              </dd>
            </>
          )}
          {kind === 'task' && (
            <>
              <dt className='text-muted-foreground'>{t('sheet.flags')}</dt>
              <dd>
                <IocaineField {...field} />
              </dd>
            </>
          )}
          {kind === 'userstory' && project.is_epics_activated && (
            <>
              <dt className='self-start pt-0.5 text-muted-foreground'>
                {t('common:terms.epic', { count: 2 })}
              </dt>
              <dd>
                <StoryEpics project={project} story={item} />
              </dd>
            </>
          )}
          <dt className='text-muted-foreground'>
            {t('common:terms.watchers')}
          </dt>
          <dd className='min-w-0'>
            <WatchersField {...field} />
          </dd>
          <dt className='text-muted-foreground'>{t('sheet.created')}</dt>
          <dd className='text-muted-foreground'>
            {item.owner_extra_info
              ? t('sheet.createdBy', {
                  date: fmt.date(item.created_date),
                  name: item.owner_extra_info.full_name_display,
                })
              : fmt.date(item.created_date)}
          </dd>
        </dl>

        <Section title={t('common:terms.description')}>
          <Description {...field} />
        </Section>

        {kind === 'epic' && (
          <Section title={t('common:terms.story', { count: 2 })}>
            <EpicStories project={project} epic={item} />
          </Section>
        )}

        {kind === 'userstory' && (
          <Section title={t('common:terms.task', { count: 2 })}>
            <StoryTasks project={project} story={item} />
          </Section>
        )}

        <CustomFields {...field} />

        <Section title={t('common:terms.attachments')}>
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
  const { t } = useTranslation('item')
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
        aria-label={t('sheet.subject')}
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
