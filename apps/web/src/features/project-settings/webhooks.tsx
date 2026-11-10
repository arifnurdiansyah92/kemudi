import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useFormat } from '@/i18n/format'
import { ChevronRight, Loader2, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Id, Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

interface Webhook {
  id: Id
  name: string
  url: string
  key: string
  logs_counter: number
}

interface WebhookLog {
  id: Id
  url: string
  status: number
  request_data: unknown
  response_data: string
  duration: number
  created: string
}

function useWebhooks(project: Project) {
  const { t } = useTranslation(['admin', 'common'])
  const qc = useQueryClient()
  const key = ['webhooks', project.id]
  const settle = () => qc.invalidateQueries({ queryKey: ['webhooks'] })
  const list = useQuery({
    queryKey: key,
    queryFn: async () =>
      (
        await api.get<Webhook[]>('/webhooks', {
          params: { project: project.id },
        })
      ).data,
  })
  const save = useMutation({
    mutationFn: (input: Partial<Webhook>) =>
      input.id
        ? api.patch(`/webhooks/${input.id}`, input)
        : api.post('/webhooks', { project: project.id, ...input }),
    onError: onFail,
    onSettled: settle,
  })
  const remove = useMutation({
    mutationFn: (w: Webhook) => api.delete(`/webhooks/${w.id}`),
    onError: onFail,
    onSettled: settle,
  })
  const test = useMutation({
    mutationFn: async (w: Webhook) =>
      (await api.post<WebhookLog>(`/webhooks/${w.id}/test`)).data,
    onSuccess: (log) =>
      log.status >= 200 && log.status < 300
        ? toast.success(t('webhooks.testOk', { status: log.status }))
        : toast.error(
            t('webhooks.testFailed', {
              status: log.status || t('webhooks.noResponse'),
            })
          ),
    onError: onFail,
    onSettled: settle,
  })
  return { list, save, remove, test }
}

export function WebhooksSettings() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  const w = useWebhooks(project)
  const [adding, setAdding] = useState(false)
  const hooks = w.list.data ?? []

  return (
    <SettingsSection
      title={t('webhooks.title')}
      description={t('webhooks.description')}
    >
      {w.list.isPending ? (
        <Skeleton className='h-16 w-full' />
      ) : (
        <ul className='grid gap-3'>
          {hooks.map((hook) => (
            <HookRow key={hook.id} hook={hook} w={w} />
          ))}
        </ul>
      )}
      {adding ? (
        <HookForm
          onCancel={() => setAdding(false)}
          onSave={(input) =>
            w.save.mutate(input, { onSuccess: () => setAdding(false) })
          }
          pending={w.save.isPending}
        />
      ) : (
        <Button
          variant='outline'
          size='sm'
          className='mt-3'
          onClick={() => setAdding(true)}
        >
          <Plus />
          {t('webhooks.add')}
        </Button>
      )}
    </SettingsSection>
  )
}

function HookRow({
  hook,
  w,
}: {
  hook: Webhook
  w: ReturnType<typeof useWebhooks>
}) {
  const { t } = useTranslation(['admin', 'common'])
  const [editing, setEditing] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const [deleting, setDeleting] = useState(false)
  if (editing)
    return (
      <li>
        <HookForm
          initial={hook}
          onCancel={() => setEditing(false)}
          onSave={(input) =>
            w.save.mutate(
              { ...input, id: hook.id },
              { onSuccess: () => setEditing(false) }
            )
          }
          pending={w.save.isPending}
        />
      </li>
    )
  return (
    <li className='rounded-md border p-3'>
      <div className='flex flex-wrap items-center gap-2'>
        <div className='min-w-0 flex-1'>
          <p className='text-sm font-medium'>{hook.name}</p>
          <p className='truncate text-xs text-muted-foreground'>{hook.url}</p>
        </div>
        <Button
          size='sm'
          variant='outline'
          onClick={() => w.test.mutate(hook)}
          disabled={w.test.isPending}
        >
          {w.test.isPending && <Loader2 className='animate-spin' />}
          {t('webhooks.sendTest')}
        </Button>
        <Button size='sm' variant='ghost' onClick={() => setEditing(true)}>
          {t('common:actions.edit')}
        </Button>
        <Button size='sm' variant='ghost' onClick={() => setDeleting(true)}>
          {t('common:actions.delete')}
        </Button>
      </div>
      <button
        onClick={() => setShowLogs((s) => !s)}
        aria-expanded={showLogs}
        className='mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground'
      >
        <ChevronRight
          className={cn('size-3 transition-transform', showLogs && 'rotate-90')}
        />
        {t('webhooks.deliveries', { total: hook.logs_counter })}
      </button>
      {showLogs && <Logs hook={hook} />}
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={t('webhooks.deleteTitle', { name: hook.name })}
        desc={t('webhooks.deleteDescription')}
        confirmText={t('webhooks.confirm')}
        destructive
        handleConfirm={() =>
          w.remove.mutate(hook, { onSuccess: () => setDeleting(false) })
        }
      />
    </li>
  )
}

function Logs({ hook }: { hook: Webhook }) {
  const { t } = useTranslation(['admin', 'common'])
  const fmt = useFormat()
  const qc = useQueryClient()
  const logs = useQuery({
    queryKey: ['webhooks', 'logs', hook.id],
    queryFn: async () =>
      (
        await api.get<WebhookLog[]>('/webhooklogs', {
          params: { webhook: hook.id },
        })
      ).data,
  })
  const resend = useMutation({
    mutationFn: (log: WebhookLog) => api.post(`/webhooklogs/${log.id}/resend`),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: ['webhooks'] }),
  })
  if (logs.isPending) return <Skeleton className='mt-2 h-10 w-full' />
  const list = logs.data ?? []
  if (!list.length)
    return (
      <p className='mt-2 text-xs text-muted-foreground'>
        {t('webhooks.nothingSent')}
      </p>
    )
  return (
    <ul className='mt-2 grid gap-1 text-xs'>
      {list.slice(0, 20).map((log) => {
        const ok = log.status >= 200 && log.status < 300
        return (
          <li key={log.id}>
            <details className='rounded border px-2 py-1'>
              <summary className='flex cursor-pointer items-center gap-2'>
                <span
                  className={cn(
                    'font-medium tabular-nums',
                    ok ? 'text-success' : 'text-destructive'
                  )}
                >
                  {log.status || t('webhooks.failed')}
                </span>
                <span className='text-muted-foreground'>
                  {fmt.timeAgo(log.created)}
                </span>
                <span className='text-muted-foreground tabular-nums'>
                  {t('webhooks.duration', {
                    ms: fmt.number(Math.round(log.duration * 1000)),
                  })}
                </span>
                <Button
                  size='sm'
                  variant='ghost'
                  className='ms-auto h-6 text-xs'
                  onClick={(e) => {
                    e.preventDefault()
                    resend.mutate(log)
                  }}
                >
                  {t('webhooks.resend')}
                </Button>
              </summary>
              <pre className='mt-2 max-h-48 overflow-auto rounded bg-muted p-2 text-[11px]'>
                {JSON.stringify(log.request_data, null, 2)}
              </pre>
              {log.response_data && (
                <pre className='mt-1 max-h-32 overflow-auto rounded bg-muted p-2 text-[11px]'>
                  {log.response_data}
                </pre>
              )}
            </details>
          </li>
        )
      })}
    </ul>
  )
}

/** A random 32-character hex secret for signing webhook requests. */
function newSecret() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

function HookForm({
  initial,
  onSave,
  onCancel,
  pending,
}: {
  initial?: Webhook
  onSave: (input: Partial<Webhook>) => void
  onCancel: () => void
  pending: boolean
}) {
  const { t } = useTranslation(['admin', 'common'])
  const [form, setForm] = useState(() => ({
    name: initial?.name ?? '',
    url: initial?.url ?? '',
    key: initial?.key ?? newSecret(),
  }))

  const valid =
    form.name.trim() && /^https?:\/\//.test(form.url) && form.key.trim()
  return (
    <form
      className='mt-3 grid gap-3 rounded-md border p-3'
      onSubmit={(e) => {
        e.preventDefault()
        if (valid) onSave(form)
      }}
    >
      <div className='grid gap-3 sm:grid-cols-2'>
        <div className='grid gap-1.5'>
          <Label htmlFor='wh-name'>{t('shared.name')}</Label>
          <Input
            id='wh-name'
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='wh-key'>{t('webhooks.secret')}</Label>
          <Input
            id='wh-key'
            value={form.key}
            onChange={(e) => setForm({ ...form, key: e.target.value })}
          />
        </div>
      </div>
      <div className='grid gap-1.5'>
        <Label htmlFor='wh-url'>{t('webhooks.url')}</Label>
        <Input
          id='wh-url'
          type='url'
          placeholder={t('webhooks.urlPlaceholder')}
          value={form.url}
          onChange={(e) => setForm({ ...form, url: e.target.value })}
        />
      </div>
      <div className='flex gap-2'>
        <Button type='submit' size='sm' disabled={!valid || pending}>
          {pending && <Loader2 className='animate-spin' />}
          {t('webhooks.save')}
        </Button>
        <Button type='button' size='sm' variant='ghost' onClick={onCancel}>
          {t('common:actions.cancel')}
        </Button>
      </div>
    </form>
  )
}
