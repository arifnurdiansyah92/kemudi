import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Eye, Heart, Search } from 'lucide-react'
import { useDiscover, useProjectToggle } from '@/lib/taiga/projects'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'

/** Public projects on this Kemudi server. */
export function Discover() {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q.trim()), 300)
    return () => window.clearTimeout(t)
  }, [q])
  const projects = useDiscover(debounced)
  const like = useProjectToggle('like')
  const watch = useProjectToggle('watch')

  return (
    <>
      <AppHeader crumbs={[{ label: 'Discover' }]} />
      <Main className='max-w-4xl'>
        <h1 className='text-2xl font-semibold tracking-tight'>Discover</h1>
        <p className='mt-1 text-sm text-muted-foreground'>
          Public projects on this server, most liked first.
        </p>
        <div className='relative mt-6 max-w-md'>
          <Search
            aria-hidden='true'
            className='absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground'
          />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder='Search public projects'
            aria-label='Search public projects'
            className='ps-8'
          />
        </div>
        <div className='mt-6'>
          {projects.isPending ? (
            <Skeleton className='h-32 w-full' />
          ) : (projects.data ?? []).length === 0 ? (
            <p className='rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground'>
              {debounced
                ? 'No public project matches.'
                : 'No public projects yet. Make a project public in its settings to list it here.'}
            </p>
          ) : (
            <ul className='divide-y rounded-lg border bg-card'>
              {projects.data!.map((p) => (
                <li
                  key={p.id}
                  className='flex flex-wrap items-center gap-4 px-5 py-4'
                >
                  <div className='min-w-0 flex-1'>
                    <Link
                      to='/p/$slug'
                      params={{ slug: p.slug }}
                      className='font-medium hover:underline hover:underline-offset-4'
                    >
                      {p.name}
                    </Link>
                    <p className='mt-0.5 line-clamp-2 text-sm text-muted-foreground'>
                      {p.description}
                    </p>
                  </div>
                  <div className='flex gap-1'>
                    <Button
                      variant='ghost'
                      size='sm'
                      aria-pressed={p.is_fan}
                      aria-label={`${p.is_fan ? 'Unlike' : 'Like'} ${p.name}`}
                      onClick={() => like.mutate(p)}
                    >
                      <Heart
                        className={cn(p.is_fan && 'fill-current text-brass')}
                      />
                      <span className='tabular-nums'>{p.total_fans}</span>
                    </Button>
                    <Button
                      variant='ghost'
                      size='sm'
                      aria-pressed={p.is_watcher}
                      aria-label={`${p.is_watcher ? 'Stop watching' : 'Watch'} ${p.name}`}
                      onClick={() => watch.mutate(p)}
                    >
                      <Eye className={cn(p.is_watcher && 'text-brass')} />
                      <span className='tabular-nums'>{p.total_watchers}</span>
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Main>
    </>
  )
}
