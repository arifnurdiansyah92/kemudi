import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy } from 'lucide-react'
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

const SERVICES: { key: keyof Modules; name: string; where: string }[] = [
  {
    key: 'github',
    name: 'GitHub',
    where:
      'Repository settings, Webhooks: content type application/json, the secret below, events "push", "issues" and "issue comment".',
  },
  {
    key: 'gitlab',
    name: 'GitLab',
    where:
      'Project settings, Webhooks: the URL below (it carries the key), triggers "push", "issues" and "comments".',
  },
  {
    key: 'bitbucket',
    name: 'Bitbucket',
    where:
      'Repository settings, Webhooks: the URL below, triggers "repository push" and issue events.',
  },
  {
    key: 'gogs',
    name: 'Gogs',
    where:
      'Repository settings, Webhooks: content type application/json, the secret below.',
  },
]

function CopyField({ label, value }: { label: string; value: string }) {
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
              .then(() => toast.success(`${label} copied`))
          }
        >
          <Copy />
          Copy
        </Button>
      </div>
    </div>
  )
}

export function IntegrationsSettings() {
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
    onSuccess: () => toast.success('Integration saved'),
    onError: onFail,
    onSettled: () => qc.invalidateQueries({ queryKey: key }),
  })

  return (
    <div className='grid gap-6'>
      <SettingsSection
        title='Commits and issues from code hosting'
        description={
          <>
            Mention an item in a commit message to link it, and add a status to
            move it: <code className='rounded bg-muted px-1'>TG-12 #done</code>{' '}
            closes item 12 with the status whose slug is <em>done</em>. Issues
            opened on the code host can create Kemudi issues too.
          </>
        }
      >
        {modules.isPending && <Skeleton className='h-40 w-full' />}
      </SettingsSection>
      {modules.data &&
        SERVICES.map(({ key: k, name, where }) => {
          const cfg = modules.data?.[k]
          if (!cfg) return null
          return (
            <SettingsSection key={k} title={name} description={where}>
              <div className='grid gap-3'>
                <CopyField label='Webhook URL' value={cfg.webhooks_url} />
                {cfg.secret && k !== 'gitlab' && (
                  <CopyField label='Secret key' value={cfg.secret} />
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
  const [text, setText] = useState(ips.join(', '))
  return (
    <div className='grid gap-1.5'>
      <Label htmlFor='origin-ips'>Accept hooks only from these addresses</Label>
      <div className='flex gap-2'>
        <Input
          id='origin-ips'
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder='Any address'
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
          Save
        </Button>
      </div>
      <p className='text-xs text-muted-foreground'>
        IP addresses or ranges (CIDR), separated by commas. Empty accepts any.
      </p>
    </div>
  )
}
