import { useState } from 'react'
import { format } from 'date-fns'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import {
  keys,
  useAddComment,
  useComments,
  useCreateTask,
  useStory,
  useTasks,
  useUpdateStory,
  useUpdateTask,
} from '@/lib/taiga/queries'
import type {
  Project,
  Task,
  UserStory,
  UserStoryDetail,
} from '@/lib/taiga/types'
import { cn, timeAgo } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { UserAvatar } from '@/components/user-avatar'
import { can, useProject, useStoryParam } from '@/features/project/use-project'
import { AssigneeMenu, Points, StatusMenu, TagList } from './parts'

/** Side sheet for the story named by `?story=<ref>`. */
export function StorySheet() {
  const project = useProject()
  const { openRef, close } = useStoryParam()
  const qc = useQueryClient()
  const detail = useStory(project.id, openRef)

  // Show the list row at once while the full story loads.
  const fromList = qc
    .getQueryData<UserStory[]>(keys.stories(project.id))
    ?.find((s) => s.ref === openRef)
  const story: UserStory | undefined = detail.data ?? fromList

  return (
    <Sheet open={openRef !== undefined} onOpenChange={(o) => !o && close()}>
      <SheetContent
        side='right'
        className='flex w-full flex-col gap-0 p-0 sm:max-w-xl'
      >
        {detail.isError && !story ? (
          <div className='p-6'>
            <SheetTitle>Story not found</SheetTitle>
            <SheetDescription className='mt-1'>
              Story #{openRef} does not exist in {project.name}, or it was
              deleted.
            </SheetDescription>
          </div>
        ) : !story ? (
          <div className='space-y-3 p-6'>
            <SheetTitle className='sr-only'>Loading story</SheetTitle>
            <Skeleton className='h-4 w-16' />
            <Skeleton className='h-7 w-3/4' />
            <Skeleton className='h-24 w-full' />
          </div>
        ) : (
          <StoryBody project={project} story={story} detail={detail.data} />
        )}
      </SheetContent>
    </Sheet>
  )
}

function StoryBody({
  project,
  story,
  detail,
}: {
  project: Project
  story: UserStory
  detail?: UserStoryDetail
}) {
  const editable = can(project, 'modify_us')
  const creator = story.owner_extra_info

  return (
    <div className='flex min-h-0 flex-1 flex-col'>
      <div className='border-b px-6 pe-12 pt-5 pb-4'>
        <SheetDescription className='text-xs tabular-nums'>
          #{story.ref}
          {story.milestone_name
            ? ` in ${story.milestone_name}`
            : ' in the backlog'}
        </SheetDescription>
        {/* Keyed on the subject so a change from elsewhere resets the field. */}
        <SubjectField
          key={story.subject}
          project={project}
          story={story}
          editable={editable}
        />
      </div>

      <div className='flex-1 overflow-y-auto'>
        <dl className='grid grid-cols-[7rem_1fr] items-center gap-x-4 gap-y-3 px-6 py-5 text-sm'>
          <dt className='text-muted-foreground'>Status</dt>
          <dd>
            <StatusMenu project={project} story={story} />
          </dd>
          <dt className='text-muted-foreground'>Assignee</dt>
          <dd>
            <AssigneeMenu project={project} story={story} showName />
          </dd>
          <dt className='text-muted-foreground'>Points</dt>
          <dd>
            <Points value={story.total_points} />
          </dd>
          {story.tags.length > 0 && (
            <>
              <dt className='text-muted-foreground'>Tags</dt>
              <dd>
                <TagList project={project} tags={story.tags} max={8} />
              </dd>
            </>
          )}
          <dt className='text-muted-foreground'>Created</dt>
          <dd className='text-muted-foreground'>
            {format(new Date(story.created_date), 'd MMM yyyy')}
            {creator && ` by ${creator.full_name_display}`}
          </dd>
        </dl>

        <Section title='Description'>
          {detail ? (
            <DescriptionField
              project={project}
              story={detail}
              editable={editable}
            />
          ) : (
            <Skeleton className='h-16 w-full' />
          )}
        </Section>

        <Section title='Tasks'>
          <TaskList project={project} story={story} />
        </Section>

        <Section title='Comments'>
          <CommentList project={project} story={story} />
        </Section>
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

function SubjectField({
  project,
  story,
  editable,
}: {
  project: Project
  story: UserStory
  editable: boolean
}) {
  const update = useUpdateStory(project)
  const [value, setValue] = useState(story.subject)

  const save = () => {
    const next = value.trim()
    if (!next) return setValue(story.subject)
    if (next !== story.subject)
      update.mutate({ id: story.id, patch: { subject: next } })
  }

  if (!editable)
    return (
      <SheetTitle className='mt-1 text-xl leading-snug font-semibold'>
        {story.subject}
      </SheetTitle>
    )

  return (
    <>
      <SheetTitle className='sr-only'>{story.subject}</SheetTitle>
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
          if (e.key === 'Escape') {
            setValue(story.subject)
          }
        }}
        className='-mx-1 mt-1 field-sizing-content w-full resize-none rounded-md bg-transparent px-1 text-xl leading-snug font-semibold outline-none hover:bg-accent/50 focus:bg-accent/50 focus-visible:ring-2 focus-visible:ring-ring'
      />
    </>
  )
}

function DescriptionField({
  project,
  story,
  editable,
}: {
  project: Project
  story: UserStoryDetail
  editable: boolean
}) {
  const update = useUpdateStory(project)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(story.description)

  if (editing)
    return (
      <form
        className='grid gap-2'
        onSubmit={(e) => {
          e.preventDefault()
          update.mutate(
            { id: story.id, patch: { description: value } },
            { onSuccess: () => setEditing(false) }
          )
        }}
      >
        <Textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          rows={8}
          autoFocus
          aria-label='Description'
          placeholder='What needs to happen, and why? Markdown works.'
        />
        <div className='flex gap-2'>
          <Button size='sm' type='submit' disabled={update.isPending}>
            {update.isPending && <Loader2 className='animate-spin' />}
            Save description
          </Button>
          <Button
            size='sm'
            variant='ghost'
            type='button'
            onClick={() => {
              setValue(story.description)
              setEditing(false)
            }}
          >
            Cancel
          </Button>
        </div>
      </form>
    )

  if (!story.description)
    return editable ? (
      <button
        onClick={() => {
          setValue('')
          setEditing(true)
        }}
        className='w-full rounded-md border border-dashed px-3 py-4 text-start text-sm text-muted-foreground hover:bg-accent/50'
      >
        Add a description
      </button>
    ) : (
      <p className='text-sm text-muted-foreground'>No description.</p>
    )

  return (
    <div className='group relative'>
      {/* description_html is rendered and sanitised by taiga-back (bleach). */}
      <div
        className='rich-text text-sm'
        dangerouslySetInnerHTML={{ __html: story.description_html }}
      />
      {editable && (
        <Button
          size='sm'
          variant='outline'
          className='mt-3'
          onClick={() => {
            setValue(story.description)
            setEditing(true)
          }}
        >
          Edit description
        </Button>
      )}
    </div>
  )
}

function TaskList({ project, story }: { project: Project; story: UserStory }) {
  const tasks = useTasks(story.id)
  const create = useCreateTask(project)
  const update = useUpdateTask(project)
  const [subject, setSubject] = useState('')
  const canEdit = can(project, 'modify_task')

  const closedStatus = project.task_statuses.find((s) => s.is_closed)
  const openStatus =
    project.task_statuses.find((s) => s.id === project.default_task_status) ??
    project.task_statuses.find((s) => !s.is_closed)

  const toggle = (task: Task, done: boolean) => {
    const status = done ? closedStatus : openStatus
    if (status) update.mutate({ task, patch: { status: status.id } })
  }

  if (tasks.isPending) return <Skeleton className='h-16 w-full' />
  const list = tasks.data ?? []
  const done = list.filter((t) => t.is_closed).length

  return (
    <div className='grid gap-1'>
      {list.length > 0 && (
        <p className='mb-1 text-xs text-muted-foreground tabular-nums'>
          {done} of {list.length} done
        </p>
      )}
      <ul className='grid gap-0.5'>
        {list.map((task) => (
          <li
            key={task.id}
            className='flex items-center gap-3 rounded-md px-1 py-1.5 text-sm hover:bg-accent/50'
          >
            <Checkbox
              id={`task-${task.id}`}
              checked={task.is_closed}
              disabled={!canEdit || !closedStatus}
              onCheckedChange={(v) => toggle(task, v === true)}
            />
            <label
              htmlFor={`task-${task.id}`}
              className={cn(
                'min-w-0 flex-1 truncate',
                task.is_closed && 'text-muted-foreground line-through'
              )}
            >
              {task.subject}
            </label>
            <span className='text-xs text-muted-foreground'>
              {task.status_extra_info.name}
            </span>
          </li>
        ))}
      </ul>
      {can(project, 'add_task') && (
        <form
          className='mt-1'
          onSubmit={(e) => {
            e.preventDefault()
            const value = subject.trim()
            if (!value) return
            create.mutate({ story, subject: value })
            setSubject('')
          }}
        >
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder='Add a task and press Enter'
            aria-label='New task'
            className='h-9 w-full rounded-md border border-dashed bg-transparent px-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-solid focus-visible:ring-2 focus-visible:ring-ring'
          />
        </form>
      )}
    </div>
  )
}

function CommentList({
  project,
  story,
}: {
  project: Project
  story: UserStory
}) {
  const comments = useComments(story.id)
  const add = useAddComment(project)
  const [text, setText] = useState('')

  return (
    <div className='grid gap-4'>
      {comments.isPending ? (
        <Skeleton className='h-12 w-full' />
      ) : comments.data && comments.data.length > 0 ? (
        <ol className='grid gap-4'>
          {comments.data.map((entry) => (
            <li key={entry.id} className='flex gap-3'>
              <UserAvatar
                user={{
                  photo: entry.user.photo,
                  full_name_display: entry.user.name,
                  color: project.members.find((m) => m.id === entry.user.pk)
                    ?.color,
                }}
                className='mt-0.5 size-7'
              />
              <div className='min-w-0 flex-1'>
                <p className='text-sm'>
                  <span className='font-medium'>{entry.user.name}</span>{' '}
                  <time
                    dateTime={entry.created_at}
                    className='text-xs text-muted-foreground'
                  >
                    {timeAgo(entry.created_at)}
                  </time>
                </p>
                <div
                  className='rich-text mt-1 text-sm'
                  dangerouslySetInnerHTML={{ __html: entry.comment_html }}
                />
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className='text-sm text-muted-foreground'>No comments yet.</p>
      )}

      {can(project, 'comment_us') && (
        <form
          className='grid gap-2'
          onSubmit={(e) => {
            e.preventDefault()
            const comment = text.trim()
            if (!comment) return
            add.mutate({ story, comment }, { onSuccess: () => setText('') })
          }}
        >
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder='Write a comment'
            aria-label='New comment'
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey))
                e.currentTarget.form?.requestSubmit()
            }}
          />
          <div className='flex items-center justify-between'>
            <span className='text-xs text-muted-foreground'>
              Ctrl+Enter to send
            </span>
            <Button
              size='sm'
              type='submit'
              disabled={!text.trim() || add.isPending}
            >
              {add.isPending && <Loader2 className='animate-spin' />}
              Comment
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}
