import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useFormat } from '@/i18n/format'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '@/stores/auth-store'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Project } from '@/lib/taiga/types'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { AppHeader } from '@/components/layout/app-header'
import { Main } from '@/components/layout/main'
import { UserAvatar } from '@/components/user-avatar'
import { useProject } from '@/features/project/use-project'
import { Timeline } from '@/features/timeline/timeline'

type MemberStats = Record<
  | 'closed_bugs'
  | 'created_bugs'
  | 'closed_tasks'
  | 'wiki_changes',
  Record<string, number>
>

const STATS = [
  ['closed_tasks', 'team.stats.closedTasks'],
  ['created_bugs', 'team.stats.createdBugs'],
  ['closed_bugs', 'team.stats.closedBugs'],
  ['wiki_changes', 'team.stats.wikiChanges'],
] as const satisfies readonly (readonly [keyof MemberStats, string])[]

export function Team({ tab = 'members' }: { tab?: 'members' | 'activity' }) {
  const { t } = useTranslation(['home', 'common'])
  const project = useProject()
  const navigate = useNavigate()
  return (
    <>
      <AppHeader
        crumbs={[
          {
            label: project.name,
            to: '/p/$slug',
            params: { slug: project.slug },
          },
          {
            label:
              tab === 'activity' ? t('team.activity') : t('common:terms.team'),
          },
        ]}
      />
      <Main width='reading'>
        <h1 className='text-2xl font-semibold tracking-tight'>
          {t('common:terms.team')}
        </h1>
        <Tabs
          value={tab}
          onValueChange={(v) =>
            navigate({
              to: v === 'activity' ? '/p/$slug/timeline' : '/p/$slug/team',
              params: { slug: project.slug },
            })
          }
          className='mt-6'
        >
          <TabsList>
            <TabsTrigger value='members'>
              {t('team.membersTab', {
                total: project.members.filter((m) => m.is_active).length,
              })}
            </TabsTrigger>
            <TabsTrigger value='activity'>{t('team.activity')}</TabsTrigger>
          </TabsList>
          <TabsContent value='members' className='mt-6'>
            <Members project={project} />
          </TabsContent>
          <TabsContent value='activity' className='mt-6'>
            <Timeline source={`project/${project.id}`} />
          </TabsContent>
        </Tabs>
      </Main>
    </>
  )
}

function Members({ project }: { project: Project }) {
  const { t } = useTranslation('home')
  const format = useFormat()
  const me = useAuthStore((s) => s.session?.user.id)
  const stats = useQuery({
    queryKey: ['member-stats', project.id],
    queryFn: async () =>
      (await api.get<MemberStats>(`/projects/${project.id}/member_stats`)).data,
  })
  const roles = [...project.roles].sort((a, b) => a.order - b.order)
  const members = project.members.filter((m) => m.is_active)

  return (
    <div className='grid gap-8'>
      {roles.map((role) => {
        const inRole = members.filter((m) => m.role === role.id)
        if (inRole.length === 0) return null
        return (
          <section key={role.id}>
            <h2 className='mb-2 text-sm font-semibold'>{role.name}</h2>
            <ul className='divide-y rounded-lg border bg-card'>
              {inRole.map((m) => (
                <li
                  key={m.id}
                  className='flex flex-wrap items-center gap-3 px-4 py-3'
                >
                  <UserAvatar user={m} className='size-9' />
                  <div className='min-w-0 flex-1'>
                    <p className='font-medium'>
                      <Link
                        to='/profile/$username'
                        params={{ username: m.username }}
                        className='underline-offset-4 hover:underline'
                      >
                        {m.full_name_display}
                      </Link>
                      {m.id === me && (
                        <span className='ms-2 text-xs font-normal text-muted-foreground'>
                          {t('team.you')}
                        </span>
                      )}
                    </p>
                    <p className='text-sm text-muted-foreground'>
                      @{m.username}
                    </p>
                  </div>
                  {stats.isPending ? (
                    <Skeleton className='h-4 w-40' />
                  ) : (
                    <dl className='flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground'>
                      {STATS.map(([key, label]) => {
                        const n = stats.data?.[key]?.[String(m.id)] ?? 0
                        if (!n) return null
                        return (
                          <div key={key} className='flex gap-1'>
                            <dd className='font-medium text-foreground tabular-nums'>
                              {format.number(n)}
                            </dd>
                            <dt>{t(label, { count: n })}</dt>
                          </div>
                        )
                      })}
                    </dl>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )
      })}
      {!project.i_am_owner && <LeaveProject project={project} />}
    </div>
  )
}

function LeaveProject({ project }: { project: Project }) {
  const { t } = useTranslation('home')
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const leave = useMutation({
    mutationFn: () => api.post(`/projects/${project.id}/leave`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      navigate({ to: '/' })
    },
    onError: onFail,
  })
  return (
    <div className='border-t pt-6'>
      <Button variant='outline' onClick={() => setOpen(true)}>
        {t('team.leave.button')}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={t('team.leave.title', { name: project.name })}
        desc={t('team.leave.description')}
        confirmText={t('team.leave.confirm')}
        destructive
        isLoading={leave.isPending}
        handleConfirm={() => leave.mutate()}
      />
    </div>
  )
}
