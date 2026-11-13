import { useFormat } from '@/i18n/format'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import {
  settingsBody,
  useAgentJobs,
  useAgentSettings,
  useForgetHostKey,
  useMachineCheck,
  useMachineKey,
  useRepos,
  useRoles,
  useSaveAgentSettings,
  type AgentSettings,
  type AgentSettingsIn,
} from '@/lib/kemudi-ai/agent'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { SettingsSection } from '@/features/project-settings/layout'
import { useProject } from '@/features/project/use-project'
import { BotAccessNotice, LastError } from './bot-access'
import { Jobs } from './jobs'
import { ProjectLlmSection } from './llm-connection'
import { Machine } from './machine'
import { DeployCommand, MergePolicy } from './merge-policy'
import { Repos } from './repos'
import { Roles } from './roles'

/** Project settings → Agent: how Awak works on this project. */
export function AgentSettingsPage() {
  const { t } = useTranslation('agent')
  const project = useProject()
  const slug = project.slug
  const canEdit = project.i_am_admin
  const settings = useAgentSettings(slug)
  const repos = useRepos(slug)
  const roles = useRoles(slug)
  const jobs = useAgentJobs(slug)

  if (settings.isPending)
    return (
      <div className='grid gap-6'>
        <Skeleton className='h-28 w-full' />
        <Skeleton className='h-64 w-full' />
      </div>
    )
  if (settings.isError)
    return (
      <p role='alert' className='text-sm text-destructive'>
        {t('unavailable')}
      </p>
    )

  // One branch is named; with several repos each merges into its own.
  const branches = [...new Set((repos.data ?? []).map((r) => r.default_branch))]
  const branch = branches.length === 1 ? branches[0] : t('merge.anyBranch')

  return (
    <div className='grid gap-6'>
      <SettingsBlocks
        slug={slug}
        settings={settings.data}
        canEdit={canEdit}
        branch={branch}
      />
      <SettingsSection
        title={t('repos.title')}
        description={t('repos.description')}
      >
        {repos.isPending ? (
          <Skeleton className='h-24 w-full' />
        ) : (
          <Repos slug={slug} repos={repos.data ?? []} canEdit={canEdit} />
        )}
      </SettingsSection>
      <SettingsSection
        title={t('roles.title')}
        description={t('roles.description')}
      >
        {roles.isPending ? (
          <Skeleton className='h-24 w-full' />
        ) : (
          <Roles
            slug={slug}
            roles={roles.data?.roles ?? []}
            repos={repos.data ?? []}
            canEdit={canEdit}
          />
        )}
      </SettingsSection>
      <SettingsSection
        title={t('jobs.title')}
        description={t('jobs.description')}
      >
        {jobs.isPending ? (
          <Skeleton className='h-24 w-full' />
        ) : (
          <Jobs slug={slug} jobs={jobs.data ?? []} />
        )}
      </SettingsSection>
    </div>
  )
}

/** Status, merge policy, model connection and machine. */
function SettingsBlocks({
  slug,
  settings,
  canEdit,
  branch,
}: {
  slug: string
  settings: AgentSettings
  canEdit: boolean
  branch: string
}) {
  const { t } = useTranslation('agent')
  const f = useFormat()
  const save = useSaveAgentSettings(slug)
  const machineKey = useMachineKey(slug)
  const check = useMachineCheck(slug)
  const forget = useForgetHostKey(slug)

  const put = (patch: Partial<AgentSettingsIn>, message: string) =>
    save.mutate(
      { ...settingsBody(settings), ...patch },
      { onSuccess: () => toast.success(message) }
    )

  return (
    <>
      <SettingsSection
        title={t('status.title')}
        description={t('status.description')}
      >
        <div className='grid gap-4'>
          <div className='flex flex-wrap items-center justify-between gap-x-6 gap-y-2'>
            <div className='flex items-center gap-3'>
              <Switch
                id='agent-enabled'
                checked={settings.enabled}
                disabled={!canEdit || save.isPending}
                onCheckedChange={(enabled) =>
                  put(
                    { enabled },
                    enabled ? t('status.turnedOn') : t('status.turnedOff')
                  )
                }
              />
              <Label htmlFor='agent-enabled' className='font-medium'>
                {t('status.label')}
              </Label>
              <span className='text-sm text-muted-foreground'>
                {settings.enabled ? t('status.on') : t('status.off')}
              </span>
              {save.isPending && (
                <Loader2 className='size-3.5 animate-spin text-muted-foreground' />
              )}
            </div>
            {settings.updated_by && settings.updated_at && (
              <p className='text-xs text-muted-foreground'>
                {t('lastChange', {
                  who: settings.updated_by,
                  when: f.date(settings.updated_at, 'dateTime'),
                })}
              </p>
            )}
          </div>
          <BotAccessNotice slug={slug} settings={settings} canEdit={canEdit} />
          <LastError settings={settings} />
        </div>
      </SettingsSection>

      <SettingsSection
        title={t('merge.title')}
        description={t('merge.description', { branch })}
      >
        <div className='grid gap-6'>
          <MergePolicy
            value={settings.merge_mode}
            branch={branch}
            canEdit={canEdit}
            pending={
              save.isPending &&
              save.variables?.merge_mode !== settings.merge_mode
            }
            onChange={(merge_mode) => put({ merge_mode }, t('merge.saved'))}
          />
          <DeployCommand
            key={settings.deploy_command ?? ''}
            value={settings.deploy_command}
            isSet={settings.deploy_command_set}
            executor={settings.executor}
            host={settings.ssh_host}
            user={settings.ssh_user}
            canEdit={canEdit}
            pending={save.isPending}
            onSave={(deploy_command) =>
              put({ deploy_command }, t('merge.deploy.saved'))
            }
          />
        </div>
      </SettingsSection>

      <SettingsSection
        title={t('llm.title')}
        description={t('llm.description')}
      >
        <ProjectLlmSection slug={slug} canEdit={canEdit} />
      </SettingsSection>

      <SettingsSection
        title={t('machine.title')}
        description={t('machine.description')}
      >
        <Machine
          key={`${settings.executor}-${settings.ssh_host}-${settings.ssh_port}-${settings.ssh_user}`}
          settings={settings}
          canEdit={canEdit}
          pending={{
            save: save.isPending,
            key: machineKey.isPending,
            check: check.isPending,
            forget: forget.isPending,
          }}
          onSave={(patch) => put(patch, t('machine.saved'))}
          onGenerateKey={() =>
            machineKey.mutate(undefined, {
              onSuccess: () => toast.success(t('key.generated')),
            })
          }
          onCheck={() => check.mutate()}
          onForgetHostKey={() =>
            forget.mutate(undefined, {
              onSuccess: () => toast.success(t('machine.hostKey.forgotten')),
            })
          }
        />
      </SettingsSection>
    </>
  )
}
