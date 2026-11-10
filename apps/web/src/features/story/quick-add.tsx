import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useCreateStory } from '@/lib/taiga/queries'
import type { Id, Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'

type QuickAddProps = {
  project: Project
  status?: Id
  milestone?: Id | null
  swimlane?: Id | null
  placeholder?: string
  className?: string
  inputRef?: React.Ref<HTMLInputElement>
}

/** One-line story creation: type a subject, press Enter, keep typing. */
export function QuickAdd({
  project,
  status,
  milestone,
  swimlane,
  placeholder = 'Add a story',
  className,
  inputRef,
}: QuickAddProps) {
  const [subject, setSubject] = useState('')
  const create = useCreateStory(project)

  return (
    <form
      className={cn(
        'flex items-center gap-2 rounded-md px-3 text-sm focus-within:bg-background focus-within:ring-2 focus-within:ring-ring',
        className
      )}
      onSubmit={(e) => {
        e.preventDefault()
        const value = subject.trim()
        if (!value) return
        create.mutate({
          subject: value,
          status,
          milestone,
          ...(swimlane ? { swimlane } : {}),
        })
        setSubject('')
      }}
    >
      <Plus
        aria-hidden='true'
        className='size-4 shrink-0 text-muted-foreground'
      />
      <input
        ref={inputRef}
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        maxLength={500}
        className='h-10 min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground'
      />
      {subject && (
        <kbd className='shrink-0 rounded border px-1.5 text-[0.6875rem] text-muted-foreground'>
          Enter
        </kbd>
      )}
    </form>
  )
}
