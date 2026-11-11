import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
import { Trans, useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

type ServiceConfig = {
  secret?: string
  webhooks_url: string
  valid_origin_ips?: string[]
}
type Modules = Partial<
  Record<'github' | 'gitlab' | 'bitbucket' | 'gogs', ServiceConfig>
>

/** Code hosts by brand name; setup steps are integrations.services.<key>. */
const SERVICES: { key: keyof Modules; name: string }[] = [
  { key: 'github', name: 'GitHub' },
  { key: 'gitlab', name: 'GitLab' },
  { key: 'bitbucket', name: 'Bitbucket' },
  { key: 'gogs', name: 'Gogs' },
]

function CopyField({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation(['admin', 'common'])
  return (
    <div className='grid gap-1.5'>
      <Label>{label}</Label>
      <div className='flex gap-2'>
        <Input
          readOnly
          value={value}
          aria-label={label}
          className='h-8 min-w-0 flex-1 text-xs'
        />
        <Button
          size='sm'
          variant='outline'
          onClick={() =>
            navigator.clipboard
              ?.writeText(value)
              .then(() => toast.success(t('integrations.copied', { label })))
          }
        >
          <Copy />
          {t('common:actions.copy')}
        </Button>
      </div>
    </div>
  )
}

export function IntegrationsSettings() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  const qc = useQueryClient()
  const key = ['modules', project.id]
  const modules = useQuery({
    queryKey: key,
    queryFn: async () =>
      (await api.get<Modules>(`/projects/${project.id}/modules`)).data,
  })
  const save = useMutation({
    mutationFn: (patch: Modules) =>
      api.patch(`/projects/${project.id}/modules`, patch),
    onSuccess: () => toast.success(t('integrations.saved')),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  })

  return (
    <div className='grid gap-6'>
      <SettingsSection
        title={t('integrations.intro.title')}
        description={
          <Trans
            t={t}
            i18nKey='integrations.intro.description'
            components={{
              code: <code className='rounded bg-muted px-1' />,
              em: <em />,
            }}
          />
        }
      >
        {modules.isPending && <Skeleton className='h-40 w-full' />}
      </SettingsSection>
      {modules.data &&
        SERVICES.map(({ key: k, name }) => {
          const cfg = modules.data?.[k]
          if (!cfg) return null
          return (
            <SettingsSection
              key={k}
              title={name}
              description={t(`integrations.services.${k}`)}
            >
              <div className='grid gap-3'>
                <CopyField
                  label={t('integrations.webhookUrl')}
                  value={cfg.webhooks_url}
                />
                {cfg.secret && k !== 'gitlab' && (
                  <CopyField
                    label={t('integrations.secret')}
                    value={cfg.secret}
                  />
                )}
                {cfg.valid_origin_ips && (
                  <OriginIps
                    key={cfg.valid_origin_ips.join()}
                    ips={cfg.valid_origin_ips}
                    onSave={(valid_origin_ips) =>
                      save.mutate({ [k]: { ...cfg, valid_origin_ips } })
                    }
                  />
                )}
              </div>
            </SettingsSection>
          )
        })}
    </div>
  )
}

function OriginIps({
  ips,
  onSave,
}: {
  ips: string[]
  onSave: (ips: string[]) => void
}) {
  const { t } = useTranslation(['admin', 'common'])
  const [text, setText] = useState(ips.join(', '))
  return (
    <div className='grid gap-1.5'>
      <Label htmlFor='origin-ips'>{t('integrations.originIps')}</Label>
      <div className='flex gap-2'>
        <Input
          id='origin-ips'
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('integrations.anyAddress')}
          className='h-8 min-w-0 flex-1 text-xs'
        />
        <Button
          size='sm'
          variant='outline'
          onClick={() =>
            onSave(
              text
                .split(/[\s,]+/)
                .map((x) => x.trim())
                .filter(Boolean)
            )
          }
        >
          {t('common:actions.save')}
        </Button>
      </div>
      <p className='text-xs text-muted-foreground'>
        {t('integrations.originIpsHint')}
      </p>
    </div>
  )
}
