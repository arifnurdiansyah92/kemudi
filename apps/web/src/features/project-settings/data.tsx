import { useMutation } from '@tanstack/react-query'
import { Copy, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useRefreshProject } from '@/lib/taiga/admin'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

const FEEDS = [
  ['userstories', 'Stories'],
  ['tasks', 'Tasks'],
  ['issues', 'Issues'],
  ['epics', 'Epics'],
] as const

export function DataSettings() {
  const project = useProject()
  return (
    <div className='grid gap-6'>
      <Export project={project} />
      <SettingsSection
        title='CSV feeds'
        description='A secret link per list that always downloads the current data as CSV, for spreadsheets and reports. Anyone with the link can read it; make a new link to cut off the old one.'
      >
        <ul className='grid gap-3'>
          {FEEDS.map(([key, label]) => (
            <Feed key={key} project={project} feed={key} label={label} />
          ))}
        </ul>
      </SettingsSection>
    </div>
  )
}

function Export({ project }: { project: Project }) {
  const run = useMutation({
    mutationFn: async () => {
      const res = await api.get<{ export_id?: string; url?: string }>(
        `/exporter/${project.id}`
      )
      return res.data
    },
    onSuccess: (data) => {
      if (data.url) window.location.assign(data.url)
      else
        toast.success(
          'Export started. You get an email with the download link when it is ready.'
        )
    },
    onError: onFail,
  })
  return (
    <SettingsSection
      title='Export'
      description='A full copy of the project (items, comments, attachments, settings) as a Taiga export file. Import it into Kemudi or Taiga to restore or move the project.'
    >
      <Button
        variant='outline'
        onClick={() => run.mutate()}
        disabled={run.isPending}
      >
        {run.isPending && <Loader2 className='animate-spin' />}
        Export project
      </Button>
    </SettingsSection>
  )
}

function Feed({
  project,
  feed,
  label,
}: {
  project: Project
  feed: (typeof FEEDS)[number][0]
  label: string
}) {
  const refresh = useRefreshProject()
  const uuid = (project as unknown as Record<string, string | null>)[
    `${feed}_csv_uuid`
  ]
  const url = uuid
    ? `${window.location.origin}${api.defaults.baseURL}/${feed}/csv?uuid=${uuid}`
    : null
  const regenerate = useMutation({
    mutationFn: () =>
      api.post(`/projects/${project.id}/regenerate_${feed}_csv_uuid`),
    onError: onFail,
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: () =>
      api.post(`/projects/${project.id}/delete_${feed}_csv_uuid`),
    onError: onFail,
    onSettled: refresh,
  })
  return (
    <li className='grid gap-1.5'>
      <span className='text-sm font-medium'>{label}</span>
      {url ? (
        <div className='flex flex-wrap gap-2'>
          <Input
            readOnly
            value={url}
            aria-label={`${label} CSV link`}
            className='h-8 min-w-60 flex-1 text-xs'
          />
          <Button
            size='sm'
            variant='outline'
            onClick={() =>
              navigator.clipboard
                ?.writeText(url)
                .then(() => toast.success('Link copied'))
            }
          >
            <Copy />
            Copy
          </Button>
          <Button size='sm' variant='ghost' onClick={() => regenerate.mutate()}>
            New link
          </Button>
          <Button size='sm' variant='ghost' onClick={() => remove.mutate()}>
            Turn off
          </Button>
        </div>
      ) : (
        <div>
          <Button
            size='sm'
            variant='outline'
            onClick={() => regenerate.mutate()}
          >
            Create link
          </Button>
        </div>
      )}
    </li>
  )
}
