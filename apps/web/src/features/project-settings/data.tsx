import { useMutation } from '@tanstack/react-query'
import { Copy, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useRefreshProject } from '@/lib/taiga/admin'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

/** Feed endpoint and its list name key in the common namespace. */
const FEEDS = [
  ['userstories', 'common:terms.story_other'],
  ['tasks', 'common:terms.task_other'],
  ['issues', 'common:terms.issue_other'],
  ['epics', 'common:terms.epic_other'],
] as const

export function DataSettings() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  return (
    <div className='grid gap-6'>
      <Export project={project} />
      <SettingsSection
        title={t('exportImport.feeds.title')}
        description={t('exportImport.feeds.description')}
      >
        <ul className='grid gap-3'>
          {FEEDS.map(([key, label]) => (
            <Feed key={key} project={project} feed={key} label={t(label)} />
          ))}
        </ul>
      </SettingsSection>
    </div>
  )
}

function Export({ project }: { project: Project }) {
  const { t } = useTranslation(['admin', 'common'])
  const run = useMutation({
    mutationFn: async () => {
      const res = await api.get<{ export_id?: string; url?: string }>(
        `/exporter/${project.id}`
      )
      return res.data
    },
    onSuccess: (data) => {
      if (data.url) window.location.assign(data.url)
      else toast.success(t('exportImport.export.started'))
    },
    onError: onFail,
  })
  return (
    <SettingsSection
      title={t('exportImport.export.title')}
      description={t('exportImport.export.description')}
    >
      <Button
        variant='outline'
        onClick={() => run.mutate()}
        disabled={run.isPending}
      >
        {run.isPending && <Loader2 className='animate-spin' />}
        {t('exportImport.export.action')}
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
  const { t } = useTranslation(['admin', 'common'])
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
            aria-label={t('exportImport.feeds.linkLabel', { label })}
            className='h-8 min-w-60 flex-1 text-xs'
          />
          <Button
            size='sm'
            variant='outline'
            onClick={() =>
              navigator.clipboard
                ?.writeText(url)
                .then(() => toast.success(t('exportImport.feeds.copied')))
            }
          >
            <Copy />
            {t('common:actions.copy')}
          </Button>
          <Button size='sm' variant='ghost' onClick={() => regenerate.mutate()}>
            {t('exportImport.feeds.newLink')}
          </Button>
          <Button size='sm' variant='ghost' onClick={() => remove.mutate()}>
            {t('exportImport.feeds.turnOff')}
          </Button>
        </div>
      ) : (
        <div>
          <Button
            size='sm'
            variant='outline'
            onClick={() => regenerate.mutate()}
          >
            {t('exportImport.feeds.create')}
          </Button>
        </div>
      )}
    </li>
  )
}
