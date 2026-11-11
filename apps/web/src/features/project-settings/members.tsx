import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, MoreHorizontal, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '@/lib/taiga/client'
import { onFail } from '@/lib/taiga/items'
import type { Id, Project } from '@/lib/taiga/types'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { UserAvatar } from '@/components/user-avatar'
import { useProject } from '@/features/project/use-project'
import { SettingsSection } from './layout'

interface Membership {
  id: Id
  user: Id | null
  email: string | null
  user_email: string | null
  full_name: string | null
  photo: string | null
  color: string | null
  role: Id
  role_name: string
  is_admin: boolean
  is_owner: boolean
  is_user_active: boolean
  created_at: string
}

function useMemberships(project: Project) {
  const { t } = useTranslation(['admin', 'common'])
  const qc = useQueryClient()
  const key = ['memberships', project.id]
  const list = useQuery({
    queryKey: key,
    queryFn: async () =>
      (
        await api.get<Membership[]>('/memberships', {
          params: { project: project.id },
          headers: { 'x-disable-pagination': '1' },
        })
      ).data,
  })
  const settle = () => {
    qc.invalidateQueries({ queryKey: key })
    qc.invalidateQueries({ queryKey: ['project'] })
  }
  const update = useMutation({
    mutationFn: ({ m, patch }: { m: Membership; patch: Partial<Membership> }) =>
      api.patch(`/memberships/${m.id}`, patch),
    onError: onFail,
    onSettled: settle,
  })
  const remove = useMutation({
    mutationFn: (m: Membership) => api.delete(`/memberships/${m.id}`),
    onError: onFail,
    onSettled: settle,
  })
  const invite = useMutation({
    mutationFn: (input: { emails: string[]; role: Id; text: string }) =>
      api.post('/memberships/bulk_create', {
        project_id: project.id,
        bulk_memberships: input.emails.map((username) => ({
          role_id: input.role,
          username,
        })),
        ...(input.text ? { invitation_extra_text: input.text } : {}),
      }),
    onSuccess: (_d, input) =>
      toast.success(
        input.emails.length === 1
          ? t('members.inviteSent', { email: input.emails[0] })
          : t('members.invitesSent', { count: input.emails.length })
      ),
    onError: onFail,
    onSettled: settle,
  })
  const resend = useMutation({
    mutationFn: (m: Membership) =>
      api.post(`/memberships/${m.id}/resend_invitation`),
    onSuccess: (_d, m) =>
      toast.success(t('members.resent', { email: m.email })),
    onError: onFail,
  })
  return { list, update, remove, invite, resend }
}

export function MembersSettings() {
  const { t } = useTranslation(['admin', 'common'])
  const project = useProject()
  const m = useMemberships(project)
  const [removing, setRemoving] = useState<Membership | null>(null)
  // Granting admin hands over every setting; ask first. Revoking is instant.
  const [promoting, setPromoting] = useState<Membership | null>(null)
  const roles = [...project.roles].sort((a, b) => a.order - b.order)
  const members = m.list.data ?? []
  const pending = members.filter((x) => !x.user)
  const active = members.filter((x) => x.user)

  return (
    <div className='grid gap-6'>
      <Invite project={project} invite={m.invite} />
      <SettingsSection
        title={t('members.title', { total: active.length })}
        description={t('members.description')}
      >
        {m.list.isPending ? (
          <Skeleton className='h-24 w-full' />
        ) : (
          <ul className='-mx-2 divide-y'>
            {active.map((x) => (
              <li
                key={x.id}
                className='flex flex-wrap items-center gap-3 px-2 py-2.5'
              >
                <UserAvatar
                  user={{
                    photo: x.photo,
                    full_name_display: x.full_name ?? x.user_email ?? '?',
                    color: x.color ?? undefined,
                  }}
                  className='size-8'
                />
                <div className='min-w-0 flex-1'>
                  <p className='truncate text-sm font-medium'>
                    {x.full_name}
                    {x.is_owner && (
                      <span className='ms-2 text-xs font-normal text-muted-foreground'>
                        {t('members.owner')}
                      </span>
                    )}
                    {!x.is_user_active && (
                      <span className='ms-2 text-xs font-normal text-muted-foreground'>
                        {t('members.deactivated')}
                      </span>
                    )}
                  </p>
                  <p className='truncate text-xs text-muted-foreground'>
                    {x.user_email}
                  </p>
                </div>
                <select
                  aria-label={t('members.roleOf', { name: x.full_name })}
                  value={x.role}
                  onChange={(e) =>
                    m.update.mutate({
                      m: x,
                      patch: { role: Number(e.target.value) },
                    })
                  }
                  className='h-8 rounded-md border bg-transparent px-2 text-sm'
                >
                  {roles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
                <button
                  disabled={x.is_owner}
                  aria-pressed={x.is_admin}
                  onClick={() =>
                    x.is_admin
                      ? m.update.mutate({ m: x, patch: { is_admin: false } })
                      : setPromoting(x)
                  }
                  className={cn(
                    'h-8 rounded-full border px-3 text-xs',
                    x.is_admin
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-accent',
                    x.is_owner && 'cursor-default opacity-70'
                  )}
                >
                  {t('members.admin')}
                </button>
                {!x.is_owner && (
                  <Button
                    variant='ghost'
                    size='icon'
                    className='size-8 text-muted-foreground'
                    aria-label={t('members.removeNamed', { name: x.full_name })}
                    onClick={() => setRemoving(x)}
                  >
                    <X />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </SettingsSection>

      {pending.length > 0 && (
        <SettingsSection
          title={t('members.pending.title', { total: pending.length })}
          description={t('members.pending.description')}
        >
          <ul className='-mx-2 divide-y'>
            {pending.map((x) => (
              <li
                key={x.id}
                className='flex items-center gap-3 px-2 py-2 text-sm'
              >
                <span className='min-w-0 flex-1 truncate'>{x.email}</span>
                <span className='text-xs text-muted-foreground'>
                  {x.role_name}
                </span>
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant='ghost'
                      size='icon'
                      className='size-8'
                      aria-label={t('members.pending.actionsFor', {
                        email: x.email,
                      })}
                    >
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align='end'>
                    <DropdownMenuItem onSelect={() => m.resend.mutate(x)}>
                      {t('members.pending.resend')}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      variant='destructive'
                      onSelect={() => m.remove.mutate(x)}
                    >
                      {t('members.pending.cancel')}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </li>
            ))}
          </ul>
        </SettingsSection>
      )}

      <ConfirmDialog
        open={!!promoting}
        onOpenChange={(o) => !o && setPromoting(null)}
        title={t('members.promote.title', {
          name: promoting?.full_name ?? '',
        })}
        desc={t('members.promote.description')}
        confirmText={t('members.promote.confirm')}
        isLoading={m.update.isPending}
        handleConfirm={() =>
          promoting &&
          m.update.mutate(
            { m: promoting, patch: { is_admin: true } },
            { onSuccess: () => setPromoting(null) }
          )
        }
      />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={t('members.remove.title', { name: removing?.full_name ?? '' })}
        desc={t('members.remove.description')}
        confirmText={t('members.remove.confirm')}
        destructive
        isLoading={m.remove.isPending}
        handleConfirm={() =>
          removing &&
          m.remove.mutate(removing, { onSuccess: () => setRemoving(null) })
        }
      />
    </div>
  )
}

function Invite({
  project,
  invite,
}: {
  project: Project
  invite: ReturnType<typeof useMemberships>['invite']
}) {
  const { t } = useTranslation(['admin', 'common'])
  const roles = [...project.roles].sort((a, b) => a.order - b.order)
  const [emails, setEmails] = useState('')
  const [role, setRole] = useState<Id>(roles[0]?.id ?? 0)
  const [text, setText] = useState('')
  const list = emails
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter(Boolean)

  return (
    <SettingsSection
      title={t('members.invite.title')}
      description={t('members.invite.description')}
    >
      <form
        className='grid gap-3'
        onSubmit={(e) => {
          e.preventDefault()
          if (!list.length) return
          invite.mutate(
            { emails: list, role, text: text.trim() },
            {
              onSuccess: () => {
                setEmails('')
                setText('')
              },
            }
          )
        }}
      >
        <div className='grid gap-3 sm:grid-cols-[1fr_12rem]'>
          <div className='grid gap-1.5'>
            <Label htmlFor='inv-emails'>{t('members.invite.emails')}</Label>
            <Input
              id='inv-emails'
              value={emails}
              onChange={(e) => setEmails(e.target.value)}
              placeholder={t('members.invite.emailsPlaceholder')}
            />
          </div>
          <div className='grid gap-1.5'>
            <Label htmlFor='inv-role'>{t('common:terms.role')}</Label>
            <select
              id='inv-role'
              value={role}
              onChange={(e) => setRole(Number(e.target.value))}
              className='h-9 rounded-md border bg-transparent px-2 text-sm'
            >
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className='grid gap-1.5'>
          <Label htmlFor='inv-text'>{t('members.invite.note')}</Label>
          <Textarea
            id='inv-text'
            rows={2}
            maxLength={255}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <div>
          <Button type='submit' disabled={!list.length || invite.isPending}>
            {invite.isPending && <Loader2 className='animate-spin' />}
            {list.length > 1
              ? t('members.invite.inviteMany', { count: list.length })
              : t('members.invite.send')}
          </Button>
        </div>
      </form>
    </SettingsSection>
  )
}
